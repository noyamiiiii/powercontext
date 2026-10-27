from __future__ import annotations

import asyncio
from pathlib import Path

from story_memory.memory import StoryMemory


def test_memory_recall_remember_and_reset(tmp_path: Path) -> None:
    async def scenario() -> None:
        memory = StoryMemory(tmp_path / "memory")
        await memory.start()
        try:
            initial = await memory.recall("player-a", "START")
            assert "离谱旅行社" in initial.context
            assert initial.turn_count == 0

            saved = await memory.remember(
                user_id="player-a",
                move="让茶壶宣布竞选市长",
                story="茶壶站上行李箱演讲，向每只鸽子承诺免费茉莉花茶。",
                turn_id="turn-1",
            )
            assert saved["status"] == "saved"

            recalled = await memory.recall("player-a", "茶壶市长的竞选承诺")
            assert "茶壶" in recalled.context
            assert "站上行李箱" in recalled.context
            assert recalled.turn_count == 1

            duplicate = await memory.remember(
                user_id="player-a",
                move="让茶壶宣布竞选市长",
                story="不应写入的重复结果",
                turn_id="turn-1",
            )
            assert duplicate["status"] == "already_saved"

            reset = await memory.reset("player-a")
            assert reset["status"] == "reset"

            after_reset = await memory.recall("player-a", "茶壶市长的竞选承诺")
            assert "茶壶" not in after_reset.context

            reopened = await memory.remember(
                user_id="player-a",
                move="让茶壶宣布竞选市长",
                story="茶壶站上行李箱演讲，向每只鸽子承诺免费茉莉花茶。",
                turn_id="turn-1",
            )
            assert reopened["status"] == "saved"

            await memory.reset("player-a")
            second_reset = await memory.recall("player-a", "茶壶市长的竞选承诺")
            assert "茶壶" not in second_reset.context

            await memory.reset("player-c")
            reset_first = await memory.recall("player-c", "START")
            assert "离谱旅行社" in reset_first.context

            isolated = await memory.recall("player-b", "茶壶市长的竞选承诺")
            assert "茶壶市长" not in isolated.context
        finally:
            await memory.close()

    asyncio.run(scenario())
