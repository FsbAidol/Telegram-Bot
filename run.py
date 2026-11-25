"""Входная точка: python run.py"""
import asyncio

from bot.main import run


async def main() -> None:
    await run()


if __name__ == "__main__":
    asyncio.run(main())
