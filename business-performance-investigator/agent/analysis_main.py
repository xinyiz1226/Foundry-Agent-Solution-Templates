"""Source-hosted analytical service; the shared engine lives at the project root."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))

from analysis.hosted import AnalysisAgent, HostedPolicy, analysis_error
from main import run_host


def build_analysis_agent(settings, credential, openai):
    policy = HostedPolicy.load(ROOT / "analysis" / "hosted-policy.json")
    return AnalysisAgent(settings, credential, openai.chat.completions, policy)


def main():
    run_host(build_analysis_agent, error_renderer=analysis_error, model_timeout=30.0)


if __name__ == "__main__":
    main()
