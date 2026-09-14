"""New synthetic fixture, not a parser or an external-data adapter."""

from .contracts import Block, Chunk, Plan, SCHEMA_VERSION


def synthetic_plan() -> Plan:
    return Plan(
        document_id="synthetic-exampleco",
        chunks=(
            Chunk("chunk-1", (
                Block("block-1", "ExampleCo revenue was USD 120 million.", "synthetic:line:1"),
                Block("block-2", "These figures are entirely fictional.", "synthetic:line:2"),
            )),
            Chunk("chunk-2", (
                Block("block-3", "ExampleCo operating income was USD 18 million.", "synthetic:line:3"),
                Block("block-4", "This sample is not investment information.", "synthetic:line:4"),
            )),
        ),
        profile_version="synthetic-financial-v1",
        schema_version=SCHEMA_VERSION,
        parser_version="pre-normalized-v1",
        model_binding="synthetic-model-v1",
    )
