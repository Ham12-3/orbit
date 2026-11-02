"""The durable run workflow (spec decision D) and the queue sweeper.

One active run per bot is enforced by RunServices.claim (a row lock on the bot), not by
Inngest concurrency, which counts executing steps and is released while a run waits.
"""

import datetime
import math
from collections.abc import Awaitable, Callable
from typing import Any

import inngest

from app.events import RUN_FINISHED, RUN_REQUESTED
from app.runs.service import ConfigurationError, RunServices


def _fail_fast_on_config[**P, T](fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return await fn(*args, **kwargs)
        except ConfigurationError as exc:
            raise inngest.NonRetriableError(str(exc)) from exc

    return wrapper


def build_run_functions(
    client: inngest.Inngest, services: RunServices
) -> list[inngest.Function[Any]]:
    settings = services.settings
    wait_slice = datetime.timedelta(seconds=settings.run_wait_slice_s)
    # check() ends the run at its deadline; the loop bound is only a backstop.
    max_slices = (
        math.ceil(
            (settings.run_timeout_s + settings.run_token_margin_s) / settings.run_wait_slice_s
        )
        + 1
    )

    async def on_failure(ctx: inngest.Context) -> None:
        original = ctx.event.data.get("event")
        error = ctx.event.data.get("error")
        run_id = original.get("data", {}).get("run_id") if isinstance(original, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        if not isinstance(run_id, str):
            return
        next_run = await services.fail(run_id, str(message or "workflow failed"))
        if next_run:
            await client.send(inngest.Event(name=RUN_REQUESTED, data={"run_id": next_run}))

    @client.create_function(
        fn_id="execute-run",
        name="Execute run",
        trigger=inngest.TriggerEvent(event=RUN_REQUESTED),
        retries=3,
        on_failure=on_failure,
    )
    async def execute_run(ctx: inngest.Context) -> dict[str, Any]:
        run_id = str(ctx.event.data["run_id"])
        if not await ctx.step.run("claim", services.claim, run_id, ctx.run_id):
            return {"run_id": run_id, "claimed": False}

        await ctx.step.run("start", _fail_fast_on_config(services.start), run_id)

        # Wait in slices: an event sent before a wait starts is not matched, and each
        # check also enforces the deadline and notices a runner that died silently.
        for i in range(max_slices):
            await ctx.step.wait_for_event(
                f"wait-{i}",
                event=RUN_FINISHED,
                if_exp="event.data.run_id == async.data.run_id",
                timeout=wait_slice,
            )
            if await ctx.step.run(f"check-{i}", services.check, run_id) == "done":
                break

        next_run = await ctx.step.run("finalize", services.finalize, run_id)
        if next_run:
            await ctx.step.send_event(
                "dispatch-next", inngest.Event(name=RUN_REQUESTED, data={"run_id": next_run})
            )
        return {"run_id": run_id, "claimed": True, "next_run": next_run}

    @client.create_function(
        fn_id="run-sweeper",
        name="Run queue sweeper",
        trigger=inngest.TriggerCron(cron="* * * * *"),
        retries=0,
    )
    async def sweep(ctx: inngest.Context) -> dict[str, Any]:
        recovered = await ctx.step.run("recover-stale", services.recover_stale)
        queued = await ctx.step.run("find-queued", services.dispatchable)
        run_ids = sorted(set(recovered) | set(queued))
        if run_ids:
            await ctx.step.send_event(
                "dispatch",
                [inngest.Event(name=RUN_REQUESTED, data={"run_id": rid}) for rid in run_ids],
            )
        return {"dispatched": run_ids}

    return [execute_run, sweep]
