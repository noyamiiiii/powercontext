from __future__ import annotations

import asyncio
from pathlib import Path

from studyloop.coach import MemoryEvidence, StudyCoach, build_study_plan


def test_plan_uses_recalled_evidence_without_inventing_context() -> None:
    evidence = (
        MemoryEvidence(
            text="薄弱点：矩阵相似与特征值的关系容易混淆。",
            score=1.0,
            matched_by=("fts",),
            citation={
                "artifact_id": "atomic-memory-test",
                "revision": "3",
                "entry_id": "entry-1",
                "entry_version_id": "version-1",
            },
        ),
        MemoryEvidence(
            text="学习偏好：先做例题，再用三句话复述。",
            score=0.8,
            matched_by=("fts",),
            citation={
                "artifact_id": "atomic-memory-test",
                "revision": "3",
                "entry_id": "entry-2",
                "entry_version_id": "version-2",
            },
        ),
    )

    plan = build_study_plan("复习矩阵相似与特征值", 30, evidence)

    assert plan.duration_minutes == 30
    assert len(plan.evidence) == 2
    assert any("容易混淆" in step for step in plan.steps)
    assert any("先做例题" in step for step in plan.steps)
    assert "2 条" in plan.recall_summary


def test_plan_is_honest_when_no_memory_matches() -> None:
    plan = build_study_plan("复习概率论", 30, ())

    assert "不会假装了解" in plan.recall_summary
    assert all("薄弱点：" not in step for step in plan.steps)


def test_powercontext_memory_roundtrip(tmp_path: Path) -> None:
    async def scenario() -> None:
        coach = StudyCoach(tmp_path / "data")
        await coach.start()
        try:
            seeded = await coach.seed_demo()
            assert seeded["memory_entries"] == 4

            plan = await coach.make_plan("复习线性代数里的矩阵相似与特征值", 30)
            assert plan.evidence
            assert any("矩阵相似" in item.text for item in plan.evidence)

            saved = await coach.record_outcome(
                goal="复习矩阵相似",
                minutes=30,
                reflection="可对角化判断还不够熟，下次先做三个反例",
                completed=True,
            )
            assert saved["status"] == "remembered"

            memories = await coach.list_memories()
            assert any("可对角化判断还不够熟" in entry["text"] for entry in memories["entries"])
        finally:
            await coach.close()

    asyncio.run(scenario())
