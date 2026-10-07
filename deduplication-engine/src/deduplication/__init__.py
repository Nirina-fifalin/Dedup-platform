from .matching import Classification, MatchConfig, Matcher, MatchResult
from .models import Correction, Issue, KnownPerson, NormalizedRecord
from .normalizer import ColumnMapping, MissingColumnsError, RecordNormalizer
from .dedupe import DedupResult, deduplicate, apply_same
from .known import GroupMatch, KnownIndex, match_to_known

__all__ = [
    "Classification", "ColumnMapping", "Correction", "Issue", "KnownPerson",
    "MatchConfig", "Matcher", "MatchResult", "MissingColumnsError",
    "NormalizedRecord", "RecordNormalizer", "DedupResult", "deduplicate",
    "apply_same", "GroupMatch", "KnownIndex", "match_to_known",
]