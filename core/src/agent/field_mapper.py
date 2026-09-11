from agent.profile import Profile

# Order matters: more specific categories are checked before generic ones
# (e.g. "preferred name" must not fall through to the full-name match).
# Public — shared with llm_mapper.py so both stay in sync on what's never auto-answered.
EEO_KEYWORDS = ("gender", "ethnicity", "hispanic", "latino", "veteran", "disability", "race")
_RESUME_KEYWORDS = ("resume", "cv")
_COVER_LETTER_KEYWORDS = ("cover letter",)
_EMAIL_KEYWORDS = ("email", "e-mail")
_PHONE_KEYWORDS = ("phone", "mobile", "telephone")
_PREFERRED_NAME_KEYWORDS = ("prefer",)
_FIRST_NAME_KEYWORDS = ("first name", "given name")
_LAST_NAME_KEYWORDS = ("last name", "surname", "family name")
_FULL_NAME_KEYWORDS = ("full name", "your name")
_LINKEDIN_KEYWORDS = ("linkedin",)
_GIT_KEYWORDS = ("github", "gitlab")


def field_haystack(field: dict) -> str:
    return " ".join(str(field.get(key, "")) for key in ("label", "name", "id", "placeholder")).lower()


def build_fill_plan(
    form_snapshot: list[dict],
    profile: Profile | None,
    cv_id: int | None,
) -> list[dict]:
    return [_map_field(field, profile, cv_id) for field in form_snapshot]


def _map_field(field: dict, profile: Profile | None, cv_id: int | None) -> dict:
    ref = field["ref"]
    haystack = field_haystack(field)

    def skip() -> dict:
        return {"ref": ref, "value": "", "action": "skip", "confidence": 0.0}

    def type_value(value: str, confidence: float) -> dict:
        return {"ref": ref, "value": value, "action": "type", "confidence": confidence}

    # Never guess on legally-sensitive voluntary disclosures, regardless of
    # profile data or confidence — this is a hard rule, not a threshold.
    if any(keyword in haystack for keyword in EEO_KEYWORDS):
        return skip()

    if field.get("type") == "file":
        if any(keyword in haystack for keyword in _COVER_LETTER_KEYWORDS) and cv_id is not None:
            return {"ref": ref, "value": "", "action": "cover_letter_upload", "confidence": 0.7}
        if any(keyword in haystack for keyword in _RESUME_KEYWORDS) and cv_id is not None:
            return {"ref": ref, "value": str(cv_id), "action": "upload", "confidence": 0.9}
        return skip()

    if any(keyword in haystack for keyword in _COVER_LETTER_KEYWORDS) and cv_id is not None:
        return {"ref": ref, "value": "", "action": "cover_letter_type", "confidence": 0.7}

    if profile is None:
        return skip()

    if any(keyword in haystack for keyword in _EMAIL_KEYWORDS):
        return type_value(profile.email, 0.95) if profile.email else skip()

    if any(keyword in haystack for keyword in _PHONE_KEYWORDS):
        return type_value(profile.phone, 0.9) if profile.phone else skip()

    if any(keyword in haystack for keyword in _PREFERRED_NAME_KEYWORDS):
        return skip()  # a nickname isn't derivable from a CV

    name_parts = profile.full_name.split() if profile.full_name else []

    if any(keyword in haystack for keyword in _FIRST_NAME_KEYWORDS):
        return type_value(name_parts[0], 0.85) if name_parts else skip()

    if any(keyword in haystack for keyword in _LAST_NAME_KEYWORDS):
        return type_value(name_parts[-1], 0.85) if len(name_parts) > 1 else skip()

    if any(keyword in haystack for keyword in _FULL_NAME_KEYWORDS):
        return type_value(profile.full_name, 0.85) if profile.full_name else skip()

    if any(keyword in haystack for keyword in _LINKEDIN_KEYWORDS):
        return type_value(profile.linkedin_url, 0.8) if profile.linkedin_url else skip()

    if any(keyword in haystack for keyword in _GIT_KEYWORDS):
        return type_value(profile.git_url, 0.8) if profile.git_url else skip()

    # Anything else here — job-specific questions, custom comboboxes, semantic
    # select matching — needs actual reasoning, not keyword matching. Skipped
    # here; ApplicationService forwards these to llm_mapper if MiMo is configured.
    return skip()
