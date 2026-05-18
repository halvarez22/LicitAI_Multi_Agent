"""
enhanced_classifier.py — Classification Engine for Enhanced Analyst Agent

This module provides:
1. Requirement classification (obligatorio/deseable/condicional)
2. Page number extraction from context
3. Clause/inciso extraction from context

Requirements: 12.1, 12.2, 12.3, 12.4, 13.1, 13.2, 13.3, 13.4, 13.5
"""
import re
from typing import List, Optional, Tuple

# Default value for missing fields as per requirements
DEFAULT_MISSING = "No especificado"

# Classification keywords as per requirements 12.1, 12.2, 12.3
OBLIGATORY_KEYWORDS = [
    "deberá",
    "es obligatorio",
    "es requisito",
    "obligatorio",
    "requerido",
    "deberá de",
    "deberá presentar",
    "deberá contar",
    "es obligatorio presentar",
    "es requisito indispensable",
    "debe cumplir",
    "debe presentar",
    "debe contar",
    "se requiere",
    "requerimiento obligatorio",
]

DESEABLE_KEYWORDS = [
    "deseable",
    "preferible",
    "se valorará",
    "preferente",
    "es deseable",
    "es preferible",
    "se considerará",
    "valoración adicional",
    "puntuación extra",
    "es un plus",
]

CONDITIONAL_KEYWORDS = [
    "cuando",
    "si ",
    "en caso de",
    "solo si",
    "únicamente cuando",
    "en el caso de que",
    "si bien",
    "a condición de",
    "siempre que",
    "dependiendo de",
    "con la condición",
    "si el licitante",
    "si el proveedor",
    "si el contratista",
]

# Page number extraction patterns
PAGE_PATTERNS = [
    # Pattern: "página X", "pagina X", "page X"
    re.compile(r"(?:página|pagina|page|pág\.?)\s*(\d+)", re.IGNORECASE),
    # Pattern: "p. X", "p X"
    re.compile(r"(?<![a-zA-Z])p\.?\s*(\d+)(?!\w)", re.IGNORECASE),
    # Pattern: "folio X", "folios X"
    re.compile(r"(?:folio|folios)\s*(\d+)", re.IGNORECASE),
    # Pattern: "documento X", "doc. X"
    re.compile(r"(?:documento|doc\.?)\s*(\d+)", re.IGNORECASE),
    # Pattern: "hoja X"
    re.compile(r"(?:hoja|hojas)\s*(\d+)", re.IGNORECASE),
]

# Clause/inciso extraction patterns
CLAUSE_PATTERNS = [
    # Pattern: "Cláusula X.Y", "Clausula X.Y", "Clause X.Y"
    re.compile(r"(?:cláusula|clausula|clause)\s*(\d+(?:\.\d+)*)", re.IGNORECASE),
    # Pattern: "Inciso a)", "inciso a)", "inc. a)"
    re.compile(r"(?:inciso|inc\.?)\s*([a-zA-Z](?:\)|\.)?)", re.IGNORECASE),
    # Pattern: "Numeral X", "numeral X"
    re.compile(r"(?:numeral)\s*(\d+(?:\.\d+)*)", re.IGNORECASE),
    # Pattern: "Artículo X", "Articulo X", "Art. X"
    re.compile(r"(?:artículo|articulo|art\.?)\s*(\d+(?:\.\d+)*)", re.IGNORECASE),
    # Pattern: "Sección X", "Seccion X"
    re.compile(r"(?:sección|seccion|sec\.?)\s*(\d+(?:\.\d+)*)", re.IGNORECASE),
    # Pattern: "Apartado X"
    re.compile(r"(?:apartado)\s*(\d+(?:\.\d+)*)", re.IGNORECASE),
    # Pattern: "Punto X"
    re.compile(r"(?:punto)\s*(\d+(?:\.\d+)*)", re.IGNORECASE),
    # Pattern: "literal a)", "literal a"
    re.compile(r"(?:literal)\s*([a-zA-Z](?:\)|\.)?)", re.IGNORECASE),
    # Pattern: Roman numerals: "I)", "II)", "III)"
    re.compile(r"\b([IVXLCDM]+)\)", re.IGNORECASE),
    # Pattern: "a)", "b)", "c)" at start of clause
    re.compile(r"(?:^|\n)\s*([a-zA-Z])\)\s*", re.MULTILINE),
]


def classify_requirement(text: str) -> Tuple[str, bool]:
    """
    Classify a requirement as obligatorio, deseable, or condicional.
    
    Args:
        text: The requirement text to classify
        
    Returns:
        Tuple of (classification, is_uncertain)
        - classification: "obligatorio", "deseable", or "condicional"
        - is_uncertain: True if classification was ambiguous and defaulted
        
    Validates: Requirements 12.1, 12.2, 12.3, 12.4
    """
    if not text or not isinstance(text, str):
        return "obligatorio", True
    
    text_lower = text.lower()
    
    # Check for conditional keywords first (they are most specific)
    for keyword in CONDITIONAL_KEYWORDS:
        if keyword in text_lower:
            return "condicional", False
    
    # Check for obligatory keywords
    for keyword in OBLIGATORY_KEYWORDS:
        if keyword in text_lower:
            return "obligatorio", False
    
    # Check for desirable keywords
    for keyword in DESEABLE_KEYWORDS:
        if keyword in text_lower:
            return "deseable", False
    
    # Default fallback as per requirement 12.4
    return "obligatorio", True


def extract_page_from_context(context: str) -> str:
    """
    Extract page number from context text.
    
    Args:
        context: The context text that may contain page references
        
    Returns:
        The extracted page number or "No especificado" if not found
        
    Validates: Requirements 13.1, 13.4
    """
    if not context or not isinstance(context, str):
        return DEFAULT_MISSING
    
    # Try each pattern
    for pattern in PAGE_PATTERNS:
        match = pattern.search(context)
        if match:
            return match.group(1)
    
    return DEFAULT_MISSING


def extract_clause_from_context(context: str) -> str:
    """
    Extract clause/inciso number from context text.
    
    Args:
        context: The context text that may contain clause references
        
    Returns:
        The extracted clause/inciso or "No especificado" if not found
        
    Validates: Requirements 13.2, 13.4
    """
    if not context or not isinstance(context, str):
        return DEFAULT_MISSING
    
    # Try each pattern
    for pattern in CLAUSE_PATTERNS:
        match = pattern.search(context)
        if match:
            return match.group(1)
    
    return DEFAULT_MISSING


class RequirementClassifier:
    """
    Classifier for requirement prioritization and categorization.
    
    This class provides comprehensive classification logic for requirements
    extracted from Mexican bidding documents (bases de licitación).
    
    Attributes:
        PRIORITY_ORDER: Priority values for each classification type
        CATEGORY_PRIORITY: Priority values for requirement categories
        
    Validates: Requirements 12.1, 12.2, 12.3, 12.4
    """
    
    # Priority order as per requirement 14.2
    PRIORITY_ORDER = {
        "obligatorio": 1,
        "deseable": 2,
        "condicional": 3,
    }
    
    # Category priority as per requirement 14.2
    CATEGORY_PRIORITY = {
        "garantías": 1,
        "documentación_legal": 2,
        "solvencia_técnica": 3,
        "propuesta_económica": 4,
        "experiencia": 3,
        "personal": 3,
        "equipamiento": 3,
        "normas": 3,
        "referencias": 3,
        "tipo_contrato": 4,
        "penalizaciones": 4,
        "pagos": 4,
    }
    
    def __init__(self):
        """Initialize the classifier with keyword lists."""
        self.obligatory_keywords = OBLIGATORY_KEYWORDS
        self.deseable_keywords = DESEABLE_KEYWORDS
        self.conditional_keywords = CONDITIONAL_KEYWORDS
    
    def classify(self, text: str) -> Tuple[str, bool]:
        """
        Classify a requirement text.
        
        Args:
            text: The requirement text to classify
            
        Returns:
            Tuple of (classification, is_uncertain)
            
        Validates: Requirements 12.1, 12.2, 12.3, 12.4
        """
        return classify_requirement(text)
    
    def classify_with_confidence(
        self, 
        text: str, 
        context: Optional[str] = None
    ) -> dict:
        """
        Classify a requirement with additional metadata.
        
        Args:
            text: The requirement text to classify
            context: Optional context for page/clause extraction
            
        Returns:
            Dictionary with classification and metadata
        """
        classification, is_uncertain = classify_requirement(text)
        
        result = {
            "clasificación": classification,
            "clasificación_incierta": is_uncertain,
        }
        
        # Add page and clause if context provided
        if context:
            result["página"] = extract_page_from_context(context)
            result["cláusula"] = extract_clause_from_context(context)
        
        return result
    
    def get_priority(self, classification: str) -> int:
        """
        Get priority value for a classification type.
        
        Args:
            classification: Classification type ("obligatorio", "deseable", "condicional")
            
        Returns:
            Priority value (lower = higher priority)
        """
        return self.PRIORITY_ORDER.get(classification, 99)
    
    def get_category_priority(self, category: str) -> int:
        """
        Get priority value for a category.
        
        Args:
            category: Category name
            
        Returns:
            Priority value (lower = higher priority)
        """
        return self.CATEGORY_PRIORITY.get(category, 99)
    
    def extract_location(self, context: str) -> dict:
        """
        Extract page and clause from context.
        
        Args:
            context: The context text containing location info
            
        Returns:
            Dictionary with página and cláusula values
        """
        return {
            "página": extract_page_from_context(context),
            "cláusula": extract_clause_from_context(context),
        }
    
    def calculate_delivery_order(
        self, 
        classification: str, 
        category: str
    ) -> int:
        """
        Calculate the delivery order for a requirement.
        
        Combines classification priority and category priority to determine
        the order in which requirements should be prepared/delivered.
        
        Args:
            classification: Classification type
            category: Category type
            
        Returns:
            Delivery order value (lower = should be delivered first)
        """
        class_priority = self.get_priority(classification)
        cat_priority = self.get_category_priority(category)
        
        # Combine priorities: classification is primary, category is secondary
        return class_priority * 100 + cat_priority


# =============================================================================
# Convenience functions (exported as per task requirements)
# =============================================================================

# These functions are already defined above, but we make them available
# as module-level exports for easier access
__all__ = [
    "classify_requirement",
    "extract_page_from_context",
    "extract_clause_from_context",
    "RequirementClassifier",
    "DEFAULT_MISSING",
    "OBLIGATORY_KEYWORDS",
    "DESEABLE_KEYWORDS",
    "CONDITIONAL_KEYWORDS",
]