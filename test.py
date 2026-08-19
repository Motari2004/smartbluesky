import asyncio
import ai

async def main() -> None:
    model = ai.get_model('zai/glm-5.2')
    messages = [ai.user_message('Why is the sky blue?')]

    async with ai.stream(model, messages) as stream:
        async for event in stream:
            if isinstance(event, ai.events.TextDelta):
                print(event.chunk, end='', flush=True)

asyncio.run(main())