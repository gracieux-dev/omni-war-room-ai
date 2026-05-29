from pydantic import BaseModel, Field
from typing import List, Literal

class CompetitorSignal(BaseModel):
    category: Literal["pricing", "stock", "marketing", "technical_issue", "other"] = Field(
        description="La catégorie du signal détecté chez le concurrent."
    )
    description: str = Field(
        description="Description précise du changement ou de l'anomalie."
    )
    severity: Literal["low", "medium", "high", "critical"] = Field(
        description="Le niveau de gravité ou d'opportunité."
    )

class MarketAnalysisOutput(BaseModel):
    competitor_name: str = Field(
        description="Nom de l'entreprise concurrente."
    )
    threat_level: int = Field(
        ..., ge=1, le=5,
        description="Score de menace de 1 (stable) à 5 (critique)."
    )
    signals_detected: List[CompetitorSignal] = Field(
        description="Liste des signaux extraits de la page."
    )
    confidence_score: float = Field(
        description="Score de confiance de 0.0 à 1.0."
    )
