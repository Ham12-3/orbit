"""Smoke-test function: proves the Dev Server can discover and invoke our app."""

import inngest

PING_EVENT = "orbit/ping"


def build_ping(client: inngest.Inngest) -> inngest.Function[object]:
    @client.create_function(fn_id="ping", trigger=inngest.TriggerEvent(event=PING_EVENT))
    async def ping(ctx: inngest.Context) -> object:
        ctx.logger.info("ping received (run %s)", ctx.run_id)
        return {"pong": True, "data": ctx.event.data}

    return ping
