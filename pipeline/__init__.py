"""
RDTII Regulatory Intelligence Agent
------------------------------------
An open-source AI pipeline that automatically finds, extracts, and maps
national regulations to the RDTII 2.0 framework (Pillar 6 & 7).

Pipeline stages:
  1. discover   — find authoritative legal sources for a country
  2. extract    — parse documents into structured legal text
  3. authority  — assign source tier and resolve conflicts
  4. retrieval  — semantic search + knowledge graph cross-references
  5. verify     — span-level hallucination check
  6. reason     — constrained LLM scoring against RDTII rubric
  7. export     — JSON-LD dataset + country brief + audit trail
"""

__version__ = "0.1.0"
__author__  = "RDTII Hackathon Team"
__license__ = "MIT"
