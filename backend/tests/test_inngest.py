from httpx import AsyncClient


async def test_inngest_endpoint_serves_our_functions(client: AsyncClient) -> None:
    response = await client.get("/api/inngest")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "dev"
    assert body["function_count"] == 1
