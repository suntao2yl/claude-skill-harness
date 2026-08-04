from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import tomllib
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from typing import Any

fcntl: Any
try:
    import fcntl
except ImportError:  # pragma: no cover - test host is normally POSIX
    fcntl = None


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "harness"
LEDGER = SKILL / "scripts" / "harness_ledger.py"
DIST = REPO / "plugins" / "harness"
DIST_SKILL = DIST / "skills" / "harness"


@contextmanager
def isolated_tmpdir():
    base = Path(os.environ.get("TMPDIR") or "/tmp")
    for attempt in range(100):
        candidate = base / f"harness-ledger-test-{os.getpid()}-{time.time_ns()}-{attempt}"
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:
            continue
        try:
            yield candidate
        finally:
            shutil.rmtree(candidate)
        return
    raise RuntimeError(f"could not allocate an isolated test directory under {base}")


def run_script(script: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    return subprocess.run(
        [sys.executable, str(script), *map(str, args)],
        cwd=str(cwd or REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def run_ledger(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return run_script(LEDGER, *args, cwd=cwd)


def ledger_argv(*args: str) -> list[str]:
    return [sys.executable, str(LEDGER), *map(str, args)]


def load_ledger_module():
    spec = importlib.util.spec_from_file_location("harness_ledger_under_test", LEDGER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {LEDGER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def contract_file(project: Path, count: int = 2) -> Path:
    path = project / "contract-input.json"
    write_json(
        path,
        {
            "acceptance": [
                {
                    "id": f"A{index:03d}",
                    "criterion": f"Observable outcome {index}",
                    "checks": [f"Check outcome {index}"],
                    "verification": {"command": f"verify-{index}"},
                }
                for index in range(1, count + 1)
            ]
        },
    )
    return path


def initialize(project: Path, count: int = 2) -> subprocess.CompletedProcess[str]:
    return run_ledger(
        "init",
        "--project-root", str(project),
        "--goal", "Ship durable behavior",
        "--contract-file", str(contract_file(project, count)),
        "--json",
    )


def legacy_state(path: Path, *, schema_version: int | None = None) -> None:
    campaign = {
        "goal": "Migrate the tracked delivery",
        "project_root": "/obsolete/absolute/path",
        "current_feature": "F001",
        "session_count": 4,
        "last_session_commit": "abc123",
        "autodrive": {"enabled": True},
    }
    if schema_version is not None:
        campaign["schema_version"] = schema_version
    write_json(path / "campaign.json", campaign)
    write_json(
        path / "features.json",
        {
            "features": [
                {
                    "id": "F001",
                    "title": "Keep the legacy outcome",
                    "description": "Preserve its legacy detail",
                    "status": "in_progress",
                    "verification": {"command": "legacy-check"},
                    "checkpoint_notes": "Completed: inspected state\nNext: finish migration\nIssues: old blocker",
                    "archived_contract": {"legacy": True},
                },
                {
                    "id": "F002",
                    "title": "Already delivered",
                    "status": "done",
                    "verification": "manual evidence",
                },
            ]
        },
    )
    write_json(
        path / "session-summary.json",
        {
            "current_feature": "F001",
            "resume_steps": ["resume from preserved handoff"],
            "known_failures": ["known legacy failure"],
        },
    )
    (path / "changes" / "CHG-001").mkdir(parents=True)
    (path / "changes" / "CHG-001" / "proposal.md").write_text("legacy proposal\n", encoding="utf-8")


class UnifiedPluginTests(unittest.TestCase):
    def test_canonical_plugin_has_one_unified_harness_skill(self) -> None:
        skill_files = sorted((REPO / "skills").rglob("SKILL.md"))
        self.assertEqual(skill_files, [SKILL / "SKILL.md"])
        self.assertEqual(sorted((SKILL / "scripts").rglob("*.py")), [LEDGER])
        self.assertFalse(
            any(path.is_file() for path in (SKILL / "resources").rglob("*"))
            if (SKILL / "resources").exists()
            else False
        )
        self.assertFalse((SKILL / "REFERENCE.md").exists())

        template = json.loads((REPO / "codex" / "plugin-manifest.json").read_text(encoding="utf-8"))
        manifest = json.loads((DIST / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest, template)
        self.assertEqual(manifest["name"], "harness")
        self.assertNotIn("hooks", manifest)
        self.assertEqual(manifest["skills"], "./skills")
        self.assertEqual(
            sorted(DIST.rglob("SKILL.md")),
            [DIST_SKILL / "SKILL.md"],
        )
        prompts = "\n".join(manifest["interface"]["defaultPrompt"])
        self.assertIn("$harness", prompts)
        self.assertNotIn("$harness-engineering", prompts)
        self.assertNotIn("$harness-pdca", prompts)

        marketplace = json.loads(
            (REPO / ".agents" / "plugins" / "marketplace.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(marketplace["name"], "harness-marketplace")
        self.assertEqual(
            [entry["name"] for entry in marketplace["plugins"]],
            ["harness"],
        )
        self.assertEqual(
            marketplace["plugins"][0]["source"]["path"],
            "./plugins/harness",
        )

        metadata = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("allow_implicit_invocation: false", metadata)
        self.assertIn("$harness", metadata)
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("one entry point, one ledger, one execution loop", skill_text.lower())
        self.assertNotIn("## passive ledger mode", skill_text.lower())
        self.assertNotIn("## pdca mode", skill_text.lower())

        expected_roles = {
            "harness_planner": ("ultra", "read-only"),
            "harness_implementer": ("high", "workspace-write"),
            "harness_checker": ("max", "read-only"),
        }
        for name, (effort, sandbox) in expected_roles.items():
            path = SKILL / "templates" / "agents" / f"{name}.toml"
            profile = tomllib.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(profile["name"], name)
            self.assertEqual(profile["model_reasoning_effort"], effort)
            self.assertEqual(profile["sandbox_mode"], sandbox)
            self.assertTrue(profile["description"])
            self.assertTrue(profile["developer_instructions"])
            if name == "harness_planner":
                self.assertIn(
                    "arrays of strings; never put objects",
                    profile["developer_instructions"],
                )
            if name == "harness_implementer":
                self.assertIn(
                    "verification is an array of objects",
                    profile["developer_instructions"],
                )

    def test_codex_distribution_is_lightweight_complete_and_in_sync(self) -> None:
        checked = run_script(REPO / "scripts" / "sync_codex_plugin.py", "--check")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        files = sorted(path for path in DIST.rglob("*") if path.is_file())
        self.assertLess(sum(path.stat().st_size for path in files), 160 * 1024)
        self.assertEqual({path.name for path in DIST.iterdir()}, {".codex-plugin", "skills"})

        canonical = {}
        for source_skill in (SKILL,):
            canonical.update(
                {
                    Path(source_skill.name) / path.relative_to(source_skill): path.read_bytes()
                    for path in source_skill.rglob("*")
                    if path.is_file()
                    and "__pycache__" not in path.parts
                    and path.suffix not in {".pyc", ".pyo"}
                }
            )
        distributed = {
            path.relative_to(DIST / "skills"): path.read_bytes()
            for path in (DIST / "skills").rglob("*")
            if path.is_file()
        }
        self.assertEqual(distributed, canonical)

    def test_skill_does_not_reintroduce_lifecycle_or_execution_orchestration(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in SKILL.rglob("*")
            if path.is_file() and path.suffix in {".md", ".py", ".yaml", ".json"}
        )
        for token in (
            "full lifecycle",
            "campaign mode",
            "engineering_advance",
            "engineering_phase",
            "campaign_init",
            "harness_transition",
            "harness_pick_next",
            "managed agents",
            "test-first",
            "release automation",
        ):
            self.assertNotIn(token, text.lower())
        self.assertNotIn("codex exec", text.lower())
        self.assertNotIn("subprocess.popen", text.lower())

    def test_pdca_enable_is_explicit_fail_closed_and_read_only_surfaces_stay_read_only(self) -> None:
        with isolated_tmpdir() as project:
            self.assertEqual(initialize(project).returncode, 0)
            path = project / ".harness" / "ledger.json"
            passive = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(passive["schema_version"], 1)

            enabled = run_ledger(
                "pdca", "enable", "--project-root", str(project),
                "--expect-sequence", "0", "--max-cycles", "3",
                "--max-do-attempts", "2", "--json",
            )
            self.assertEqual(enabled.returncode, 0, enabled.stderr)
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(state["schema_version"], 2)
            self.assertEqual(state["checkpoint"]["sequence"], 1)
            self.assertEqual(state["pdca"]["phase"], "plan")
            self.assertEqual(state["pdca"]["scope"], ["A001", "A002"])
            self.assertEqual(state["pdca"]["policy"]["plan"]["reasoning_effort"], "ultra")
            self.assertEqual(state["pdca"]["policy"]["do"]["reasoning_effort"], "high")
            self.assertEqual(state["pdca"]["policy"]["check"]["reasoning_effort"], "max")
            backups = list(project.glob(".harness-legacy-backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(
                json.loads((backups[0] / "ledger.json").read_text(encoding="utf-8")),
                passive,
            )

            before = path.read_bytes()
            before_stat = path.stat()
            for command in (
                ("status", "--project-root", str(project), "--json"),
                ("validate", "--project-root", str(project), "--json"),
                ("resume", "--project-root", str(project), "--json"),
                ("pdca", "status", "--project-root", str(project), "--json"),
            ):
                result = run_ledger(*command)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(path.stat().st_mtime_ns, before_stat.st_mtime_ns)

            bypass = run_ledger(
                "checkpoint", "--project-root", str(project), "--complete", "A001",
                "--evidence-json", json.dumps({
                    "kind": "test", "ref": "bypass", "result": "pass", "revision": "r1",
                }),
            )
            self.assertEqual(bypass.returncode, 2)
            self.assertIn("deterministic PDCA Act", bypass.stderr)
            self.assertEqual(path.read_bytes(), before)

    def test_pdca_happy_path_binds_plan_candidate_and_check_before_act(self) -> None:
        with isolated_tmpdir() as project:
            self.assertEqual(initialize(project).returncode, 0)
            enabled = run_ledger(
                "pdca", "enable", "--project-root", str(project),
                "--expect-sequence", "0", "--json",
            )
            self.assertEqual(enabled.returncode, 0, enabled.stderr)
            reports = project / ".harness" / "reports"
            plan = reports / "cycle-001-plan.json"
            write_json(plan, {
                "contract_sha256": json.loads(
                    (project / ".harness" / "ledger.json").read_text(encoding="utf-8")
                )["contract"]["sha256"],
                "acceptance_ids": ["A001", "A002"],
                "plan_revision": "plan-r1",
                "summary": "Implement both observable outcomes",
                "steps": ["Implement outcome one", "Implement outcome two"],
                "verification": ["Run verify-1", "Run verify-2"],
                "risks": [],
            })
            recorded_plan = run_ledger(
                "pdca", "record-plan", "--project-root", str(project),
                "--expect-sequence", "1", "--artifact-file", str(plan), "--json",
            )
            self.assertEqual(recorded_plan.returncode, 0, recorded_plan.stderr)

            do = reports / "cycle-001-do.json"
            write_json(do, {
                "plan_revision": "plan-r1",
                "candidate_revision": "candidate-r1",
                "summary": "Implemented both outcomes",
                "changes": ["Changed outcome one", "Changed outcome two"],
                "verification": [
                    {"ref": "verify-1", "result": "pass"},
                    {"ref": "verify-2", "result": "pass"},
                ],
            })
            recorded_do = run_ledger(
                "pdca", "record-do", "--project-root", str(project),
                "--expect-sequence", "2", "--artifact-file", str(do), "--json",
            )
            self.assertEqual(recorded_do.returncode, 0, recorded_do.stderr)

            check = reports / "cycle-001-check.json"
            check_payload = {
                "plan_revision": "plan-r1",
                "candidate_revision": "candidate-r1",
                "summary": "Independent checks passed",
                "criteria": [
                    {
                        "acceptance_id": "A001", "result": "pass", "action": None,
                        "evidence_ref": "verify-1 independently passed",
                    },
                    {
                        "acceptance_id": "A002", "result": "success", "action": None,
                        "evidence_ref": "verify-2 independently passed",
                    },
                ],
            }
            write_json(check, check_payload)
            recorded_check = run_ledger(
                "pdca", "record-check", "--project-root", str(project),
                "--expect-sequence", "3", "--artifact-file", str(check), "--json",
            )
            self.assertEqual(recorded_check.returncode, 0, recorded_check.stderr)

            write_json(check, {**check_payload, "summary": "tampered after Check"})
            tampered = run_ledger(
                "pdca", "act", "--project-root", str(project),
                "--expect-sequence", "4", "--json",
            )
            self.assertEqual(tampered.returncode, 2)
            self.assertIn("artifact sha256", tampered.stderr)
            write_json(check, check_payload)
            acted = run_ledger(
                "pdca", "act", "--project-root", str(project),
                "--expect-sequence", "4", "--json",
            )
            self.assertEqual(acted.returncode, 0, acted.stderr)
            state = json.loads(
                (project / ".harness" / "ledger.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["pdca"]["status"], "complete")
            self.assertEqual(state["pdca"]["phase"], "act")
            self.assertEqual(state["checkpoint"]["sequence"], 5)
            self.assertEqual(state["checkpoint"]["completed_acceptance"], ["A001", "A002"])
            evidence = state["checkpoint"]["evidence"][-1]
            self.assertEqual(evidence["kind"], "pdca-check")
            self.assertEqual(evidence["revision"], "candidate-r1")
            self.assertEqual(evidence["acceptance_ids"], ["A001", "A002"])

    def test_pdca_rejects_stale_or_incomplete_check_and_blocks_on_budget(self) -> None:
        with isolated_tmpdir() as project:
            self.assertEqual(initialize(project).returncode, 0)
            self.assertEqual(
                run_ledger(
                    "pdca", "enable", "--project-root", str(project),
                    "--expect-sequence", "0", "--max-cycles", "1",
                    "--max-do-attempts", "1",
                ).returncode,
                0,
            )
            state_path = project / ".harness" / "ledger.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            reports = project / ".harness" / "reports"
            plan = reports / "plan.json"
            write_json(plan, {
                "contract_sha256": state["contract"]["sha256"],
                "acceptance_ids": ["A001", "A002"],
                "plan_revision": "plan-r1", "summary": "Plan",
                "steps": ["Implement"], "verification": ["Verify"], "risks": [],
            })
            self.assertEqual(
                run_ledger(
                    "pdca", "record-plan", "--project-root", str(project),
                    "--expect-sequence", "1", "--artifact-file", str(plan),
                ).returncode,
                0,
            )
            stale_bytes = state_path.read_bytes()
            stale = run_ledger(
                "pdca", "record-plan", "--project-root", str(project),
                "--expect-sequence", "1", "--artifact-file", str(plan),
            )
            self.assertEqual(stale.returncode, 2)
            self.assertIn("stale PDCA write", stale.stderr)
            self.assertEqual(state_path.read_bytes(), stale_bytes)

            do = reports / "do.json"
            write_json(do, {
                "plan_revision": "plan-r1", "candidate_revision": "candidate-r1",
                "summary": "Do", "changes": ["Changed"],
                "verification": [{"ref": "verify", "result": "fail"}],
            })
            self.assertEqual(
                run_ledger(
                    "pdca", "record-do", "--project-root", str(project),
                    "--expect-sequence", "2", "--artifact-file", str(do),
                ).returncode,
                0,
            )
            invalid_check = reports / "invalid-check.json"
            write_json(invalid_check, {
                "plan_revision": "plan-r1", "candidate_revision": "wrong-revision",
                "summary": "Invalid", "criteria": [
                    {
                        "acceptance_id": "A001", "result": "fail", "action": "fix",
                        "evidence_ref": "failed",
                    }
                ],
            })
            before_invalid = state_path.read_bytes()
            rejected = run_ledger(
                "pdca", "record-check", "--project-root", str(project),
                "--expect-sequence", "3", "--artifact-file", str(invalid_check),
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("candidate_revision", rejected.stderr)
            self.assertEqual(state_path.read_bytes(), before_invalid)

            check = reports / "check.json"
            write_json(check, {
                "plan_revision": "plan-r1", "candidate_revision": "candidate-r1",
                "summary": "Needs a fix", "criteria": [
                    {
                        "acceptance_id": "A001", "result": "fail", "action": "fix",
                        "evidence_ref": "verify failed",
                    },
                    {
                        "acceptance_id": "A002", "result": "pass", "action": None,
                        "evidence_ref": "independent observation passed",
                    },
                ],
            })
            self.assertEqual(
                run_ledger(
                    "pdca", "record-check", "--project-root", str(project),
                    "--expect-sequence", "3", "--artifact-file", str(check),
                ).returncode,
                0,
            )
            recorded_ledger = state_path.read_bytes()
            tampered_state = json.loads(recorded_ledger)
            tampered_criterion = tampered_state["pdca"]["events"][-1]["criteria"][0]
            tampered_criterion["result"] = "pass"
            tampered_criterion["action"] = None
            write_json(state_path, tampered_state)
            projection_mismatch = run_ledger(
                "validate", "--project-root", str(project), "--json",
            )
            self.assertEqual(projection_mismatch.returncode, 2)
            self.assertIn("event projection does not match artifact content", projection_mismatch.stderr)
            refused_act = run_ledger(
                "pdca", "act", "--project-root", str(project),
                "--expect-sequence", "4", "--json",
            )
            self.assertEqual(refused_act.returncode, 2)
            self.assertIn("event projection does not match artifact content", refused_act.stderr)
            state_path.write_bytes(recorded_ledger)
            acted = run_ledger(
                "pdca", "act", "--project-root", str(project),
                "--expect-sequence", "4", "--json",
            )
            self.assertEqual(acted.returncode, 0, acted.stderr)
            blocked = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(blocked["pdca"]["status"], "blocked")
            self.assertIn(
                "do-attempt-budget-exhausted",
                blocked["pdca"]["events"][-1]["reason_codes"],
            )

            refused_restart = run_ledger(
                "pdca", "restart", "--project-root", str(project),
                "--expect-sequence", "5", "--reason", "Fix approach approved",
            )
            self.assertEqual(refused_restart.returncode, 2)
            self.assertIn("higher --max-cycles", refused_restart.stderr)
            restarted = run_ledger(
                "pdca", "restart", "--project-root", str(project),
                "--expect-sequence", "5", "--reason", "Fix approach approved",
                "--max-cycles", "2", "--json",
            )
            self.assertEqual(restarted.returncode, 0, restarted.stderr)
            resumed = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(resumed["pdca"]["status"], "active")
            self.assertEqual(resumed["pdca"]["phase"], "plan")
            self.assertEqual(resumed["pdca"]["cycle"], 2)

    def test_init_preflight_is_atomic_and_existing_state_is_preserved(self) -> None:
        with isolated_tmpdir() as project:
            invalid = project / "invalid.json"
            write_json(invalid, {"acceptance": []})
            failed = run_ledger(
                "init", "--project-root", str(project), "--goal", "A goal",
                "--contract-file", str(invalid),
            )
            self.assertEqual(failed.returncode, 2)
            self.assertFalse((project / ".harness").exists())

            created = initialize(project)
            self.assertEqual(created.returncode, 0, created.stderr)
            ledger = project / ".harness" / "ledger.json"
            self.assertEqual([path.name for path in ledger.parent.iterdir()], ["ledger.json"])
            self.assertEqual(stat.S_IMODE(ledger.stat().st_mode), 0o600)
            original = ledger.read_bytes()

            repeated = initialize(project)
            self.assertEqual(repeated.returncode, 2)
            self.assertEqual(ledger.read_bytes(), original)
            validated = run_ledger("validate", "--project-root", str(project), "--json")
            self.assertEqual(validated.returncode, 0, validated.stderr)

    def test_checkpoint_requires_linked_evidence_and_never_mutates_contract(self) -> None:
        with isolated_tmpdir() as project:
            self.assertEqual(initialize(project).returncode, 0)
            path = project / ".harness" / "ledger.json"
            before = json.loads(path.read_text(encoding="utf-8"))
            contract_before = before["contract"]
            bytes_before = path.read_bytes()

            missing_evidence = run_ledger(
                "checkpoint", "--project-root", str(project), "--complete", "A001"
            )
            self.assertEqual(missing_evidence.returncode, 2)
            self.assertEqual(path.read_bytes(), bytes_before)

            failing_evidence = run_ledger(
                "checkpoint", "--project-root", str(project),
                "--complete", "A001",
                "--evidence-json", json.dumps({
                    "kind": "test", "ref": "verify-1", "result": "fail", "revision": "r1",
                }),
            )
            self.assertEqual(failing_evidence.returncode, 2)
            self.assertEqual(path.read_bytes(), bytes_before)

            incomplete_links = run_ledger(
                "checkpoint", "--project-root", str(project),
                "--complete", "A001", "--complete", "A002",
                "--evidence-json", json.dumps({
                    "kind": "test", "ref": "verify-1", "result": "pass", "revision": "r1",
                    "acceptance_ids": ["A001"],
                }),
            )
            self.assertEqual(incomplete_links.returncode, 2)
            self.assertEqual(path.read_bytes(), bytes_before)

            completed = run_ledger(
                "checkpoint", "--project-root", str(project),
                "--complete", "A001",
                "--completed-step", "Implemented outcome 1",
                "--next-step", "Continue outcome 2",
                "--evidence-json", json.dumps({
                    "kind": "test", "ref": "verify-1", "result": "pass", "revision": "r1",
                }),
                "--summary", "A001 is ready for handoff", "--json",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            after = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(after["contract"], contract_before)
            self.assertEqual(after["checkpoint"]["completed_acceptance"], ["A001"])
            evidence = after["checkpoint"]["evidence"][0]
            self.assertEqual(evidence["acceptance_ids"], ["A001"])
            self.assertEqual(evidence["revision"], "r1")
            self.assertIn("observed_at", evidence)

            rejected_host_fields = run_ledger(
                "checkpoint", "--project-root", str(project),
                "--evidence-json", json.dumps({
                    "kind": "test", "ref": "verify-1", "result": "pass",
                    "revision": "r1", "git" + "_head": "abc123",
                    "worktree" + "_fingerprint": "legacy-host-detail",
                }),
            )
            self.assertEqual(rejected_host_fields.returncode, 2)
            self.assertIn("unsupported keys", rejected_host_fields.stderr)

            for placeholder in ("TBD", "todo", "<source-or-artifact-revision>"):
                placeholder_revision = run_ledger(
                    "checkpoint", "--project-root", str(project),
                    "--complete", "A002",
                    "--evidence-json", json.dumps({
                        "kind": "test", "ref": "unverified placeholder", "result": "pass",
                        "revision": placeholder,
                    }),
                )
                self.assertEqual(placeholder_revision.returncode, 2)
                self.assertIn("non-placeholder", placeholder_revision.stderr)

            result_alias = run_ledger(
                "checkpoint", "--project-root", str(project),
                "--complete", "A002",
                "--evidence-json", json.dumps({
                    "kind": "test", "ref": "unsupported result alias", "result": "passed",
                    "revision": "r2",
                }),
            )
            self.assertEqual(result_alias.returncode, 2)
            self.assertIn("latest new passing evidence", result_alias.stderr)

            reopened = run_ledger(
                "checkpoint", "--project-root", str(project),
                "--evidence-json", json.dumps({
                    "kind": "test", "ref": "verify-1 regression", "result": "fail",
                    "revision": "r2", "acceptance_ids": ["A001"],
                }),
                "--summary", "A001 regressed", "--json",
            )
            self.assertEqual(reopened.returncode, 0, reopened.stderr)
            reopened_state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(reopened_state["checkpoint"]["completed_acceptance"], [])

            recompleted = run_ledger(
                "checkpoint", "--project-root", str(project),
                "--complete", "A001",
                "--evidence-json", json.dumps({
                    "kind": "test", "ref": "verify-1 fixed", "result": "success",
                    "revision": "r3",
                }),
                "--json",
            )
            self.assertEqual(recompleted.returncode, 0, recompleted.stderr)
            after = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(after["checkpoint"]["completed_acceptance"], ["A001"])

            unsupported = json.loads(json.dumps(after))
            unsupported["checkpoint"]["completed_acceptance"].append("A002")
            write_json(path, unsupported)
            invalid_completion = run_ledger("validate", "--project-root", str(project))
            self.assertEqual(invalid_completion.returncode, 2)
            self.assertIn("lacks latest passing evidence", invalid_completion.stderr)

            dangling = json.loads(json.dumps(after))
            dangling["checkpoint"]["evidence"][0]["acceptance_ids"] = ["A999"]
            write_json(path, dangling)
            invalid_reference = run_ledger("validate", "--project-root", str(project))
            self.assertEqual(invalid_reference.returncode, 2)
            self.assertIn("unknown ids", invalid_reference.stderr)

            stale_latest = json.loads(json.dumps(after))
            stale_latest["checkpoint"]["evidence"].append({
                "kind": "test",
                "ref": "later regression",
                "result": "failed",
                "observed_at": "2099-01-01T00:00:00Z",
                "revision": "r4",
                "acceptance_ids": ["A001"],
            })
            write_json(path, stale_latest)
            invalid_latest = run_ledger("validate", "--project-root", str(project))
            self.assertEqual(invalid_latest.returncode, 2)
            self.assertIn("lacks latest passing evidence", invalid_latest.stderr)

            write_json(path, after)
            after["contract"]["acceptance"][0]["criterion"] = "tampered"
            write_json(path, after)
            invalid = run_ledger("validate", "--project-root", str(project))
            self.assertEqual(invalid.returncode, 2)
            self.assertIn("digest", invalid.stderr)

    def test_status_validate_and_resume_are_read_only(self) -> None:
        with isolated_tmpdir() as project:
            self.assertEqual(initialize(project).returncode, 0)
            path = project / ".harness" / "ledger.json"
            before = path.read_bytes()
            before_stat = path.stat()
            for command in ("status", "validate", "resume"):
                result = run_ledger(command, "--project-root", str(project), "--json")
                self.assertEqual(result.returncode, 0, result.stderr)
            child = project / "nested" / "work"
            child.mkdir(parents=True)
            from_child = run_ledger("resume", "--json", cwd=child)
            self.assertEqual(from_child.returncode, 0, from_child.stderr)
            after_stat = path.stat()
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(after_stat.st_mtime_ns, before_stat.st_mtime_ns)

    def test_raw_acceptance_is_rejected_and_legacy_state_gets_migration_hint(self) -> None:
        with isolated_tmpdir() as project:
            self.assertEqual(initialize(project).returncode, 0)
            path = project / ".harness" / "ledger.json"
            state = json.loads(path.read_text(encoding="utf-8"))
            state["contract"]["acceptance"][0].pop("id")
            write_json(path, state)
            for command in ("status", "validate", "resume"):
                result = run_ledger(command, "--project-root", str(project), "--json")
                self.assertEqual(result.returncode, 2)
                self.assertIn("canonical normalized form", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

        with isolated_tmpdir() as project:
            legacy_state(project / ".harness")
            for command in ("status", "validate", "resume"):
                result = run_ledger(command, "--project-root", str(project))
                self.assertEqual(result.returncode, 2)
                self.assertIn("resume --migrate", result.stderr)
            checkpoint = run_ledger(
                "checkpoint", "--project-root", str(project), "--completed-step", "unsafe"
            )
            self.assertEqual(checkpoint.returncode, 2)
            self.assertIn("resume --migrate", checkpoint.stderr)
            init = run_ledger(
                "init", "--project-root", str(project), "--goal", "Do not overwrite legacy",
                "--contract-file", str(contract_file(project)),
            )
            self.assertEqual(init.returncode, 2)
            self.assertIn("resume --migrate", init.stderr)

        with isolated_tmpdir() as project:
            nested = project / ".engineering" / "implementation" / ".harness"
            legacy_state(nested)
            checkpoint = run_ledger(
                "checkpoint", "--project-root", str(project), "--completed-step", "unsafe"
            )
            self.assertEqual(checkpoint.returncode, 2)
            self.assertIn("resume --migrate", checkpoint.stderr)
            self.assertFalse((project / ".harness").exists())

    def test_open_issues_append_until_explicitly_cleared(self) -> None:
        with isolated_tmpdir() as project:
            self.assertEqual(initialize(project).returncode, 0)
            first = run_ledger(
                "checkpoint", "--project-root", str(project), "--open-issue", "first"
            )
            second = run_ledger(
                "checkpoint", "--project-root", str(project), "--open-issue", "second"
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            path = project / ".harness" / "ledger.json"
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(state["checkpoint"]["open_issues"], ["first", "second"])

            cleared = run_ledger(
                "checkpoint", "--project-root", str(project),
                "--clear-open-issues", "--open-issue", "replacement",
            )
            self.assertEqual(cleared.returncode, 0, cleared.stderr)
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(state["checkpoint"]["open_issues"], ["replacement"])

    @unittest.skipIf(fcntl is None, "POSIX flock is unavailable")
    def test_checkpoint_directory_flock_prevents_lost_concurrent_updates(self) -> None:
        with isolated_tmpdir() as project:
            self.assertEqual(initialize(project).returncode, 0)
            harness = project / ".harness"
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            descriptor = os.open(harness, flags)
            env = os.environ.copy()
            env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
            blocked = None
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                blocked = subprocess.Popen(
                    ledger_argv(
                        "checkpoint", "--project-root", str(project),
                        "--completed-step", "held-step",
                    ),
                    cwd=str(REPO),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                time.sleep(0.25)
                self.assertIsNone(blocked.poll(), "checkpoint ignored the directory flock")
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
            assert blocked is not None
            stdout, stderr = blocked.communicate(timeout=10)
            self.assertEqual(blocked.returncode, 0, stderr or stdout)

            processes = [
                subprocess.Popen(
                    ledger_argv(
                        "checkpoint", "--project-root", str(project),
                        "--completed-step", f"concurrent-{index}",
                    ),
                    cwd=str(REPO),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for index in range(12)
            ]
            for process in processes:
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0, stderr or stdout)

            ledger = harness / "ledger.json"
            state = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(state["checkpoint"]["sequence"], 13)
            self.assertEqual(
                set(state["checkpoint"]["completed_steps"]),
                {"held-step", *(f"concurrent-{index}" for index in range(12))},
            )
            self.assertEqual({path.name for path in harness.iterdir()}, {"ledger.json"})
            self.assertEqual(stat.S_IMODE(ledger.stat().st_mode), 0o600)

    def test_checkpoint_falls_back_to_a_bounded_temporary_directory_lock(self) -> None:
        with isolated_tmpdir() as project:
            self.assertEqual(initialize(project).returncode, 0)
            module = load_ledger_module()
            module._fcntl = None
            observed_lock: list[bool] = []
            original_write = module.write_json_atomic

            def checking_write(path, payload):
                observed_lock.append((project / ".harness" / ".checkpoint-lock").is_dir())
                return original_write(path, payload)

            module.write_json_atomic = checking_write
            args = module.build_parser().parse_args(
                [
                    "checkpoint",
                    "--project-root", str(project),
                    "--completed-step", "fallback-step",
                    "--json",
                ]
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(module.cmd_checkpoint(args), 0)
            self.assertEqual(observed_lock, [True])
            self.assertFalse((project / ".harness" / ".checkpoint-lock").exists())

            lock_directory = project / ".harness" / ".checkpoint-lock"
            lock_directory.mkdir()
            module.FALLBACK_LOCK_TIMEOUT_SECONDS = 0
            with self.assertRaisesRegex(module.LedgerError, "timed out waiting"):
                with module.exclusive_harness_lock(project):
                    self.fail("an existing fallback lock must not be bypassed")
            lock_directory.rmdir()

    def test_source_is_confined_to_exact_project_legacy_locations(self) -> None:
        with isolated_tmpdir() as container:
            project = container / "project"
            project.mkdir()
            external = container / ".harness"
            legacy_state(external)
            alias = container / "legacy-alias"
            alias.symlink_to(external, target_is_directory=True)
            for source in (external, container, project, alias):
                rejected = run_ledger(
                    "resume", "--project-root", str(project), "--migrate",
                    "--source", str(source),
                )
                self.assertEqual(rejected.returncode, 2)
                self.assertIn("--source must resolve exactly", rejected.stderr)
            self.assertFalse((project / ".harness").exists())
            self.assertFalse(list(project.glob(".harness-legacy-backup-*")))

            self.assertEqual(initialize(project).returncode, 0)
            rejected_with_ledger = run_ledger(
                "resume", "--project-root", str(project), "--migrate",
                "--source", str(external),
            )
            self.assertEqual(rejected_with_ledger.returncode, 2)

        with isolated_tmpdir() as project:
            source = project / ".harness"
            legacy_state(source)
            target = project / "outside-target"
            target.write_text("outside\n", encoding="utf-8")
            (source / "unsafe-link").symlink_to(target)
            rejected_symlink = run_ledger(
                "resume", "--project-root", str(project), "--migrate"
            )
            self.assertEqual(rejected_symlink.returncode, 2)
            self.assertIn("must not contain symlinks", rejected_symlink.stderr)
            self.assertFalse((source / "ledger.json").exists())
            self.assertFalse(list(project.glob(".harness-legacy-backup-*")))

    def test_schema1_root_migration_is_backed_up_atomic_and_idempotent(self) -> None:
        with isolated_tmpdir() as project:
            source = project / ".harness"
            legacy_state(source)
            legacy_campaign = (source / "campaign.json").read_bytes()
            migrated = run_ledger(
                "resume", "--project-root", str(project), "--migrate", "--json"
            )
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            ledger = source / "ledger.json"
            state = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(state["schema_version"], 1)
            self.assertEqual(
                state["contract"]["acceptance"][0]["criterion"],
                "Keep the legacy outcome — Preserve its legacy detail",
            )
            self.assertEqual(state["checkpoint"]["completed_acceptance"], [])
            legacy_done = [
                item for item in state["checkpoint"]["evidence"]
                if item.get("acceptance_ids") == ["F002"]
            ]
            self.assertEqual(len(legacy_done), 1)
            self.assertEqual(legacy_done[0]["kind"], "legacy-claim")
            self.assertEqual(legacy_done[0]["result"], "unknown")
            self.assertEqual(legacy_done[0]["revision"], "abc123")
            self.assertEqual(state["checkpoint"]["next_steps"], ["resume from preserved handoff"])
            self.assertIn("known legacy failure", state["checkpoint"]["open_issues"])
            self.assertRegex(state["migration"]["source_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual({path.name for path in source.iterdir()}, {"ledger.json"})
            self.assertEqual(stat.S_IMODE(ledger.stat().st_mode), 0o600)

            backups = list(project.glob(".harness-legacy-backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "campaign.json").read_bytes(), legacy_campaign)
            self.assertEqual(
                (backups[0] / "changes" / "CHG-001" / "proposal.md").read_text(encoding="utf-8"),
                "legacy proposal\n",
            )
            before = ledger.read_bytes()
            repeated = run_ledger(
                "resume", "--project-root", str(project), "--migrate",
                "--source", str(source), "--json",
            )
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(ledger.read_bytes(), before)
            self.assertEqual(len(list(project.glob(".harness-legacy-backup-*"))), 1)

    def test_nested_migration_and_ambiguous_or_invalid_preflight(self) -> None:
        with isolated_tmpdir() as project:
            nested = project / ".engineering" / "implementation" / ".harness"
            legacy_state(nested, schema_version=2)
            marker = project / "legacy-command-must-not-run"
            features = json.loads((nested / "features.json").read_text(encoding="utf-8"))
            features["features"][0]["verification"] = {
                "command": f"{sys.executable} -c 'open({str(marker)!r}, \"w\").close()'"
            }
            write_json(nested / "features.json", features)
            original = (nested / "features.json").read_bytes()
            migrated = run_ledger(
                "resume", "--project-root", str(project), "--migrate", "--json"
            )
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            self.assertTrue((project / ".harness" / "ledger.json").exists())
            self.assertFalse(marker.exists(), "migration executed a legacy command")
            self.assertEqual((nested / "features.json").read_bytes(), original)
            self.assertEqual(len(list(project.glob(".harness-legacy-backup-*"))), 1)

        with isolated_tmpdir() as project:
            root_source = project / ".harness"
            nested = project / ".engineering" / "implementation" / ".harness"
            legacy_state(root_source)
            legacy_state(nested)
            ambiguous = run_ledger("resume", "--project-root", str(project), "--migrate")
            self.assertEqual(ambiguous.returncode, 2)
            self.assertFalse((root_source / "ledger.json").exists())
            self.assertFalse(list(project.glob(".harness-legacy-backup-*")))
            explicit = run_ledger(
                "resume", "--project-root", str(project), "--migrate",
                "--source", str(root_source), "--json",
            )
            self.assertEqual(explicit.returncode, 0, explicit.stderr)
            self.assertTrue((root_source / "ledger.json").exists())
            self.assertFalse((nested / "ledger.json").exists())

        with isolated_tmpdir() as project:
            source = project / ".harness"
            write_json(source / "campaign.json", {"goal": "broken"})
            (source / "features.json").write_text("{not json", encoding="utf-8")
            failed = run_ledger("resume", "--project-root", str(project), "--migrate")
            self.assertEqual(failed.returncode, 2)
            self.assertFalse((source / "ledger.json").exists())
            self.assertFalse(list(project.glob(".harness-legacy-backup-*")))

        with isolated_tmpdir() as project:
            source = project / ".harness"
            legacy_state(source, schema_version=99)
            future = run_ledger("resume", "--project-root", str(project), "--migrate")
            self.assertEqual(future.returncode, 2)
            self.assertIn("unsupported legacy schema_version", future.stderr)
            self.assertFalse((source / "ledger.json").exists())
            self.assertFalse(list(project.glob(".harness-legacy-backup-*")))

        with isolated_tmpdir() as project:
            source = project / ".harness"
            legacy_state(source, schema_version=2)
            summary = json.loads((source / "session-summary.json").read_text(encoding="utf-8"))
            summary["current_feature"] = "F002"
            write_json(source / "session-summary.json", summary)
            conflict = run_ledger("resume", "--project-root", str(project), "--migrate")
            self.assertEqual(conflict.returncode, 2)
            self.assertIn("references conflict", conflict.stderr)
            self.assertFalse((source / "ledger.json").exists())
            self.assertFalse(list(project.glob(".harness-legacy-backup-*")))


if __name__ == "__main__":
    unittest.main()
