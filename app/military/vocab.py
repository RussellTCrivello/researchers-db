"""Military Organization — controlled vocabularies.

Every enumerated value in the system lives here so the schema, the business
rules, the API and the interface share one source of truth.  Vocabularies are
owner-reviewable: they are data, not scattered literals (design record §7.3).
"""
from __future__ import annotations

# --- entity catalogue -------------------------------------------------------
ENTITY_TYPES = [
    "region", "division", "classification", "commander", "unit",
    "deployment", "mission", "armament", "holding", "training",
    "assignment", "note",
]

# entity slug -> human label (design record §7.2)
ENTITY_LABELS = {
    "region": "Region",
    "division": "Division",
    "classification": "Classification",
    "commander": "Commander",
    "unit": "Military Unit",
    "deployment": "Operational Deployment",
    "mission": "Mission",
    "armament": "Armament",
    "holding": "Unit Armament",
    "training": "Training",
    "assignment": "Command Assignment",
    "note": "Note",
}

# --- enumerated vocabularies ------------------------------------------------
UNIT_STATUSES = [
    "Active", "Training", "Standby", "Mobilized", "Attached",
    "Reserve", "Reorganizing", "Stand-down", "Disbanded",
]
UNIT_ECHELONS = [
    "Brigade", "Division", "Regiment", "Battalion", "Company",
    "Platoon", "Squadron", "Detachment",
]
REGION_TYPES = ["Theater", "Region", "Zone", "Area"]
DIVISION_TYPES = ["Mechanized", "Armored", "Infantry", "Artillery", "Support", "Airborne"]
CLASS_CATEGORIES = ["Combat", "Support", "Reserve", "Training"]
READINESS_TIERS = ["High", "Medium", "Low"]

COMMANDER_STATUSES = ["Active", "Reserve", "Retired"]
COMMANDER_RANKS = [
    "General", "Brigadier General", "Colonel", "Lieutenant Colonel",
    "Major", "Captain", "Lieutenant",
]
BRANCHES = ["Army", "Air Force", "Navy", "Joint"]

DEPLOYMENT_STATUSES = ["Planned", "Active", "Completed", "Suspended"]
DEPLOYMENT_TYPES = ["Operational", "Training", "Humanitarian", "Peacekeeping", "Reserve"]

MISSION_STATUSES = ["Planned", "Ongoing", "Executed", "Cancelled"]
MISSION_TYPES = [
    "Combat", "Reconnaissance", "Logistics", "Training",
    "Humanitarian", "Peacekeeping",
]

ARMAMENT_CATEGORIES = ["Weapons", "Vehicles", "Artillery", "Aircraft", "Communications", "Support"]
HOLDING_CONDITIONS = ["Serviceable", "Limited", "Unserviceable", "In Refit"]

TRAINING_TYPES = ["Exercise", "Course", "Certification", "Drill", "Joint Exercise"]
TRAINING_ASSESSMENTS = ["Excellent", "Satisfactory", "Needs Improvement", "Unsatisfactory"]

ASSIGNMENT_ROLES = [
    "Commanding Officer", "Deputy Commander", "Chief of Staff", "Acting Commander",
]

# note targets allowed by the polymorphic link (design record §7.5, §8.1)
NOTE_TARGET_TYPES = [
    "unit", "deployment", "mission", "training", "assignment",
    "commander", "armament", "region", "division",
]

# --- state transition tables (design record §8.3) ---------------------------
# An empty list marks a terminal state.  Unit status is deliberately
# set-valued only: the transition policy for units is owner-reviewable.
DEPLOYMENT_TRANSITIONS = {
    "Planned": ["Active", "Suspended"],
    "Active": ["Completed", "Suspended"],
    "Suspended": ["Active", "Completed"],
    "Completed": [],
}
MISSION_TRANSITIONS = {
    "Planned": ["Ongoing", "Cancelled"],
    "Ongoing": ["Executed", "Cancelled"],
    "Executed": [],
    "Cancelled": [],
}
COMMANDER_TRANSITIONS = {
    "Active": ["Reserve"],
    "Reserve": ["Active", "Retired"],
    "Retired": [],
}

# maps an entity slug to its vocabulary fields (drives API + UI validation)
VOCAB_FIELDS = {
    "region": {"region_type": REGION_TYPES},
    "division": {"division_type": DIVISION_TYPES},
    "classification": {"category": CLASS_CATEGORIES, "readiness_tier": READINESS_TIERS},
    "commander": {"rank_title": COMMANDER_RANKS, "branch": BRANCHES,
                  "status": COMMANDER_STATUSES},
    "unit": {"echelon": UNIT_ECHELONS, "status": UNIT_STATUSES},
    "deployment": {"deployment_type": DEPLOYMENT_TYPES, "status": DEPLOYMENT_STATUSES},
    "mission": {"mission_type": MISSION_TYPES, "status": MISSION_STATUSES},
    "armament": {"category": ARMAMENT_CATEGORIES},
    "holding": {"condition": HOLDING_CONDITIONS},
    "training": {"training_type": TRAINING_TYPES, "assessment": TRAINING_ASSESSMENTS},
    "assignment": {"role": ASSIGNMENT_ROLES},
    "note": {"entity_type": NOTE_TARGET_TYPES},
}
