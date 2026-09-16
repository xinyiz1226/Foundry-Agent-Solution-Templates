"""Example domain configurations; execution contains no domain-specific branches."""

from .contracts import ExtractionProfile, FieldSpec, FieldType, RecordSchema


FINANCIAL_PROFILE = ExtractionProfile(
    version="financial-example-v1",
    schema=RecordSchema(
        version="financial-flat-v1",
        fields=(
            FieldSpec("metric", FieldType.ENUM, "The explicitly stated financial metric.",
                      choices=("revenue", "operating_income")),
            FieldSpec("value", FieldType.NUMBER, "The explicitly stated value in USD millions."),
            FieldSpec("unit", FieldType.ENUM, "The explicitly stated unit.",
                      choices=("USD_millions",)),
        ),
    ),
    instructions=(
        "Extract only explicitly stated revenue and operating income in USD millions. "
        "Copy the stated numeric value; do not convert currencies or units, calculate, "
        "infer, or invent facts. Return zero records if no qualifying facts are stated, "
        "or multiple records when multiple qualifying facts are stated. "
        "Cite current-chunk source block IDs for every field; do not supply quotations."
    ),
)


SUPPORT_PROFILE = ExtractionProfile(
    version="abcd-support-v1",
    schema=RecordSchema(
        version="support-flat-v1",
        fields=(
            FieldSpec("customer_issue_or_request", FieldType.TEXT,
                      "The customer's explicitly stated concern or request."),
            FieldSpec("product_or_service", FieldType.TEXT,
                      "The explicitly named product or service.", nullable=True),
            FieldSpec("attempted_action", FieldType.TEXT,
                      "An action explicitly reported as performed, not merely suggested.",
                      nullable=True),
            FieldSpec("stated_outcome", FieldType.TEXT,
                      "An explicitly stated result or current disposition.", nullable=True),
            FieldSpec("outcome_status", FieldType.ENUM,
                      "Only an explicitly supported resolved, unresolved, or pending status.",
                      nullable=True, choices=("resolved", "unresolved", "pending")),
        ),
    ),
    instructions=(
        "Use only original customer and agent utterances supplied as dialogue blocks. "
        "Never use scenario metadata, delexed text, action turns, hidden labels, policy "
        "knowledge, or external facts. Produce one record per distinct customer concern "
        "or request, consolidating repetitions of that concern. A request for information "
        "is a valid concern; do not invent a product defect. Suggestions are not performed "
        "actions. Do not claim resolution without explicit evidence. Use null for facts "
        "not stated or statuses not explicitly supported, with an empty evidence list. "
        "Every nonnull field must cite current-chunk original-utterance block IDs. "
        "Return zero records when no customer concern is stated. Do not supply quotations."
    ),
)
