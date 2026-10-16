"""Model registry.

Importing this package registers every mapper on ``Base.metadata``. Alembic's
env.py imports it for exactly that reason — without it, autogenerate produces an
empty migration and reports success.
"""

from app.models.account import (  # noqa: F401
    Account,
    AccountAlias,
    AccountList,
    AccountListMember,
    Contact,
    ContactSuggestion,
    Run,
)
from app.models.config import (  # noqa: F401
    EnrichmentConfig,
    InstallationMode,
    IntegrationCredential,
    LlmConfig,
    ModelAvailability,
    OrgProfile,
    ProofPoint,
    ResearchSource,
    SalesRules,
    ScoringConfig,
    ServiceCatalog,
    SignalType,
    WritingSample,
)

__all__ = [
    "Account",
    "AccountAlias",
    "AccountList",
    "AccountListMember",
    "Contact",
    "ContactSuggestion",
    "IntegrationCredential",
    "EnrichmentConfig",
    "InstallationMode",
    "LlmConfig",
    "ModelAvailability",
    "OrgProfile",
    "ProofPoint",
    "ResearchSource",
    "SalesRules",
    "ScoringConfig",
    "Run",
    "ServiceCatalog",
    "SignalType",
    "WritingSample",
]
from app.models.campaign import (  # noqa: F401
    CadenceShape,
    CampaignQueue,
    CampaignQueueContact,
    CampaignQueueMember,
    DeferredEnrolment,
    LgmIdentity,
    OutreachCampaign,
    OutreachCampaignSource,
    OutreachSequence,
)
from app.models.content import Draft, Touch  # noqa: F401
from app.models.context import AccountContext, Qualification  # noqa: F401
from app.models.execution import ExecutionRecord  # noqa: F401
from app.models.governance import (  # noqa: F401
    Approval,
    ApprovalSample,
    Evaluation,
)
from app.models.cost import ModelPrice, SerpCall  # noqa: F401
from app.models.identity import AuditLog, Organization, RoleGrid, User  # noqa: F401
from app.models.prep import SalesPrep  # noqa: F401
from app.models.research import ResearchCoverage  # noqa: F401
from app.models.signal import (  # noqa: F401
    Evidence,
    Signal,
    signal_evidence,
)
from app.models.strategy import (  # noqa: F401
    PersonaServiceScore,
    Strategy,
    StrategyThread,
    StrategyAngle,
)
