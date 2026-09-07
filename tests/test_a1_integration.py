from __future__ import annotations

from pathlib import Path


def test_a1_has_no_new_capability_id() -> None:
    root = Path(__file__).resolve().parents[1]
    definitions = root / "nova_os" / "capability_definitions.py"
    if definitions.exists():
        text = definitions.read_text(encoding="utf-8-sig")
        assert 'capability_id="core_intelligence"' not in text
        assert 'capability_id="project_intelligence"' not in text


def test_installed_tool_is_intrinsic_and_read_only() -> None:
    root = Path(__file__).resolve().parents[1]
    tool = root / "tools" / "core_intelligence.py"
    text = tool.read_text(encoding="utf-8-sig")
    assert "get_nova_core_context" in text
    for forbidden in (
        "subprocess.run(",
        "os.system(",
        "git push",
        "git commit",
        "git reset",
        "git clean",
        "approve_action",
        "promote_to_active",
        "activate_production",
    ):
        assert forbidden not in text


def test_installed_agent_has_per_session_broker_if_agent_present() -> None:
    root = Path(__file__).resolve().parents[1]
    agent = root / "agent.py"
    if not agent.exists():
        return
    text = agent.read_text(encoding="utf-8-sig")
    assert "from nova_intelligence.context_broker import ContextBroker" in text
    assert "self.core_intelligence = ContextBroker()" in text


def test_installed_catalog_exposes_core_tool_without_capability_if_present() -> None:
    root = Path(__file__).resolve().parents[1]
    catalog = root / "nova_os" / "catalog.py"
    if not catalog.exists():
        return
    text = catalog.read_text(encoding="utf-8-sig")
    assert "from tools.core_intelligence import CORE_INTELLIGENCE_TOOLS" in text
    assert "control_tools=(*CAPABILITY_CONTROL_TOOLS, *CORE_INTELLIGENCE_TOOLS)" in text


def test_prompt_contract_is_shadow_safe_if_prompts_present() -> None:
    root = Path(__file__).resolve().parents[1]
    prompts = root / "prompts.py"
    if not prompts.exists():
        return
    text = prompts.read_text(encoding="utf-8-sig")
    assert "NOVA CORE INTELLIGENCE A1" in text
    assert "SHADOW_ONLY" in text
    assert "UNKNOWN means do not guess" in text
    assert "does not grant permission" in text


def test_project_state_git_probe_is_fixed_and_shell_free() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "nova_intelligence" / "project_state.py").read_text(encoding="utf-8")
    assert "shell=False" in text
    assert '["git", *args]' in text
    for forbidden in (
        '"add"',
        '"commit"',
        '"push"',
        '"reset"',
        '"clean"',
        '"checkout"',
        '"switch"',
        '"stash"',
    ):
        # The implementation may mention Git concepts in prose, but the fixed
        # command invocations must not contain mutation subcommands.
        assert f'_run_git(repo_root, {forbidden}' not in text
        assert f'_run_git(requested_root, {forbidden}' not in text


def test_package_patch_programs_apply_and_revert_on_guarded_fixture(tmp_path: Path) -> None:
    package_root = Path(__file__).resolve().parents[1]
    integration = package_root / "integration"
    if not integration.exists():
        # Installed-repo test path: the package-only integration programs are
        # intentionally not copied into the NOVA source tree.
        return

    import importlib.util

    def load(name: str):
        spec = importlib.util.spec_from_file_location(name, integration / f"{name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    agent_patch = load("agent_patch")
    prompt_patch = load("prompt_patch")
    cap_patch = load("capability_integration")

    repo = tmp_path / "repo"
    (repo / "nova_os").mkdir(parents=True)

    agent_text = (
        "from nova_lab.service import DevelopmentService\n"
        "class Assistant:\n"
        "    def x(self):\n"
        "        self.skill_registry = skills\n"
    )
    agent_path = repo / "agent.py"
    agent_path.write_text(agent_text, encoding="utf-8")
    agent_patch.BASE_BLOB_SHA = agent_patch.git_blob_sha(agent_path)

    prompt_path = repo / "prompts.py"
    prompt_path.write_text('SYSTEM_PROMPT = """base"""\n', encoding="utf-8")
    prompt_patch.BASE_BLOB_SHA = prompt_patch.git_blob_sha(prompt_path)

    catalog_text = (
        "from tools.capabilities import CAPABILITY_CONTROL_TOOLS\n"
        "def build():\n"
        "    return CapabilityManager(\n"
        "        registry,\n"
        "        control_tools=CAPABILITY_CONTROL_TOOLS,\n"
        "    )\n"
    )
    catalog_path = repo / "nova_os" / "catalog.py"
    catalog_path.write_text(catalog_text, encoding="utf-8")
    cap_patch.BASE_BLOB_SHA = cap_patch.git_blob_sha(catalog_path)

    assert agent_patch.apply(repo)
    assert prompt_patch.apply(repo)
    assert cap_patch.apply(repo)

    agent_patch.check(repo)
    prompt_patch.check(repo)
    cap_patch.check(repo)

    assert agent_patch.revert(repo)
    assert prompt_patch.revert(repo)
    assert cap_patch.revert(repo)

    assert "ContextBroker" not in agent_path.read_text(encoding="utf-8")
    assert "NOVA CORE INTELLIGENCE A1" not in prompt_path.read_text(encoding="utf-8")
    assert "CORE_INTELLIGENCE_TOOLS" not in catalog_path.read_text(encoding="utf-8")


def test_package_verifier_is_fail_closed_for_native_gates() -> None:
    root = Path(__file__).resolve().parents[1]
    verifier = root / "VERIFY-A1.ps1"
    if not verifier.exists():
        # Installed-repo test path: package transaction scripts are not copied.
        return
    text = verifier.read_text(encoding="utf-8-sig")
    assert "Full NOVA pytest failed with exit code" in text
    assert "NOVA chat smoke failed with exit code" in text
    assert "NOVA tool-driver failed with exit code" in text
    assert "Targeted A1 tests failed with exit code" in text
    assert "Do not inspect LASTEXITCODE" in text
    # Regression guard for the V1 verifier bug: the parent gate wrapper must
    # not infer native success from a child-scriptblock LASTEXITCODE.
    assert "$code = $LASTEXITCODE" not in text


def test_package_installer_can_recover_exact_failed_transaction() -> None:
    root = Path(__file__).resolve().parents[1]
    installer = root / "INSTALL-A1.ps1"
    if not installer.exists():
        return
    text = installer.read_text(encoding="utf-8-sig")
    assert "Preserve-And-Clean-KnownFailedA1" in text
    assert "NOVA-A1-FAILED-TRANSACTION-RECOVERY-" in text
    assert "Refusing automatic recovery because unrelated A1 work may be present" in text
    assert "UNCOMMITTED - verifier must pass before checkpoint" in text
    assert "Integrated A1 Python syntax check failed" in text
