import argparse
import json
import re
import sys
from pathlib import Path


SCHEMA_VERSION = "1.1"
SUPPORTED_INPUT_TYPES = {"text", "textarea", "select", "multiselect"}
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
TOP_LEVEL_FIELDS = {"$schema", "schema_version", "id", "name", "description", "prompt", "inputs"}
PROMPT_FIELDS = {"reviewer_role", "objective", "instructions", "review_sections"}
REVIEW_SECTION_FIELDS = {"title", "instruction"}
INPUT_FIELDS = {
    "id",
    "label",
    "help",
    "type",
    "required",
    "default",
    "placeholder",
    "prompt_template",
    "options",
}
OPTION_FIELDS = {"value", "label", "prompt_value"}


class SkillValidationError(ValueError):
    pass


class SkillStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self._skills = {}

    def load(self):
        skills = {}
        if not self.directory.is_dir():
            raise SkillValidationError(f"Skill directory does not exist: {self.directory}")

        for path in sorted(self.directory.glob("*.json")):
            if path.name == "skill.schema.json":
                continue
            try:
                skill = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SkillValidationError(f"{path.name}: unable to read valid JSON: {exc}") from exc
            self._validate_skill(skill, path.name)
            if skill["id"] in skills:
                raise SkillValidationError(f"{path.name}: duplicate skill id {skill['id']!r}")
            skills[skill["id"]] = skill

        if not skills:
            raise SkillValidationError(f"No review skills were found in {self.directory}")
        self._skills = skills
        return self

    def list_skills(self):
        return [self._skills[key] for key in sorted(self._skills, key=lambda item: self._skills[item]["name"].lower())]

    def get(self, skill_id):
        return self._skills.get(str(skill_id or "").strip())

    def compose(self, skill_id, answers=None):
        skill = self.get(skill_id)
        if not skill:
            raise SkillValidationError(f"Unknown review skill: {skill_id or '(missing)'}")
        if answers is None:
            answers = {}
        if not isinstance(answers, dict):
            raise SkillValidationError("Skill answers must be a JSON object.")

        prompt = skill["prompt"]
        selected_instructions = []
        known_ids = {item["id"] for item in skill["inputs"]}
        unknown_ids = sorted(set(answers) - known_ids)
        if unknown_ids:
            raise SkillValidationError(f"Unknown answer field(s): {', '.join(unknown_ids)}")

        for field in skill["inputs"]:
            value = answers.get(field["id"], field.get("default"))
            if self._is_empty(value):
                if field.get("required", False):
                    raise SkillValidationError(f"{field['label']} is required.")
                continue
            prompt_value = self._resolve_prompt_value(field, value)
            selected_instructions.append(field["prompt_template"].replace("{value}", prompt_value))

        configured_instructions = [instruction.strip() for instruction in prompt["instructions"] if instruction.strip()]
        if selected_instructions:
            configured_instructions.extend(selected_instructions)

        skills_prompt = "\n".join(
            [prompt["reviewer_role"].strip(), prompt["objective"].strip(), *configured_instructions]
        )

        return {
            "skill_id": skill["id"],
            "skill_name": skill["name"],
            "skills_prompt": skills_prompt,
            "review_goal": prompt["objective"].strip(),
            "prompt_configuration": {
                "reviewer_role": prompt["reviewer_role"].strip(),
                "objective": prompt["objective"].strip(),
                "instructions": configured_instructions,
                "review_sections": prompt["review_sections"],
            },
        }

    def _validate_skill(self, skill, filename):
        if not isinstance(skill, dict):
            raise SkillValidationError(f"{filename}: the root value must be an object")
        self._reject_unknown_fields(skill, TOP_LEVEL_FIELDS, filename)
        if "$schema" in skill and not isinstance(skill["$schema"], str):
            raise SkillValidationError(f"{filename}: $schema must be a string")
        self._require_string(skill, "schema_version", filename)
        if skill["schema_version"] != SCHEMA_VERSION:
            raise SkillValidationError(f"{filename}: schema_version must be {SCHEMA_VERSION!r}")
        for field in ("id", "name", "description"):
            self._require_string(skill, field, filename)
        if not IDENTIFIER_PATTERN.fullmatch(skill["id"]):
            raise SkillValidationError(f"{filename}: id must use lowercase letters, digits, and hyphens")

        prompt = skill.get("prompt")
        if not isinstance(prompt, dict):
            raise SkillValidationError(f"{filename}: prompt must be an object")
        self._reject_unknown_fields(prompt, PROMPT_FIELDS, f"{filename}.prompt")
        for field in ("reviewer_role", "objective"):
            self._require_string(prompt, field, f"{filename}.prompt")
        instructions = prompt.get("instructions")
        if not isinstance(instructions, list) or not all(isinstance(item, str) and item.strip() for item in instructions):
            raise SkillValidationError(f"{filename}: prompt.instructions must be a non-empty string array")
        review_sections = prompt.get("review_sections")
        if not isinstance(review_sections, list) or not review_sections:
            raise SkillValidationError(f"{filename}: prompt.review_sections must be a non-empty array")
        for index, section in enumerate(review_sections):
            location = f"{filename}.prompt.review_sections[{index}]"
            if not isinstance(section, dict):
                raise SkillValidationError(f"{location}: section must be an object")
            self._reject_unknown_fields(section, REVIEW_SECTION_FIELDS, location)
            for field in REVIEW_SECTION_FIELDS:
                self._require_string(section, field, location)

        inputs = skill.get("inputs")
        if not isinstance(inputs, list):
            raise SkillValidationError(f"{filename}: inputs must be an array")
        seen_ids = set()
        for index, field in enumerate(inputs):
            location = f"{filename}.inputs[{index}]"
            if not isinstance(field, dict):
                raise SkillValidationError(f"{location}: input must be an object")
            self._reject_unknown_fields(field, INPUT_FIELDS, location)
            for key in ("id", "label", "type", "prompt_template"):
                self._require_string(field, key, location)
            if not IDENTIFIER_PATTERN.fullmatch(field["id"]):
                raise SkillValidationError(f"{location}: invalid input id")
            if field["id"] in seen_ids:
                raise SkillValidationError(f"{location}: duplicate input id {field['id']!r}")
            seen_ids.add(field["id"])
            if field["type"] not in SUPPORTED_INPUT_TYPES:
                raise SkillValidationError(f"{location}: unsupported input type {field['type']!r}")
            if "{value}" not in field["prompt_template"]:
                raise SkillValidationError(f"{location}: prompt_template must contain {{value}}")
            if "required" in field and not isinstance(field["required"], bool):
                raise SkillValidationError(f"{location}: required must be true or false")
            for optional_text in ("help", "placeholder"):
                if optional_text in field and not isinstance(field[optional_text], str):
                    raise SkillValidationError(f"{location}: {optional_text} must be a string")
            self._validate_options(field, location)
            self._validate_default(field, location)

    def _validate_options(self, field, location):
        options = field.get("options", [])
        if field["type"] in {"select", "multiselect"} and not options:
            raise SkillValidationError(f"{location}: selection inputs require options")
        if options and field["type"] not in {"select", "multiselect"}:
            raise SkillValidationError(f"{location}: only selection inputs may define options")
        seen_values = set()
        for index, option in enumerate(options):
            option_location = f"{location}.options[{index}]"
            if not isinstance(option, dict):
                raise SkillValidationError(f"{option_location}: option must be an object")
            self._reject_unknown_fields(option, OPTION_FIELDS, option_location)
            for key in OPTION_FIELDS:
                self._require_string(option, key, option_location)
            if option["value"] in seen_values:
                raise SkillValidationError(f"{option_location}: duplicate option value")
            seen_values.add(option["value"])

    def _validate_default(self, field, location):
        if "default" not in field:
            return
        default = field["default"]
        if field["type"] == "multiselect":
            if not isinstance(default, list) or not all(isinstance(item, str) for item in default):
                raise SkillValidationError(f"{location}: multiselect default must be a string array")
            values = {option["value"] for option in field.get("options", [])}
            if not set(default).issubset(values):
                raise SkillValidationError(f"{location}: default contains an unknown option")
            return
        if not isinstance(default, str):
            raise SkillValidationError(f"{location}: default must be a string")
        if field["type"] == "select":
            values = {option["value"] for option in field.get("options", [])}
            if default not in values:
                raise SkillValidationError(f"{location}: default contains an unknown option")

    def _resolve_prompt_value(self, field, value):
        if field["type"] == "select":
            if not isinstance(value, str):
                raise SkillValidationError(f"{field['label']} must contain one selection.")
            options = {option["value"]: option["prompt_value"] for option in field["options"]}
            if value not in options:
                raise SkillValidationError(f"{field['label']} contains an unknown selection.")
            return options[value]
        if field["type"] == "multiselect":
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise SkillValidationError(f"{field['label']} must contain a selection list.")
            values = value
            options = {option["value"]: option["prompt_value"] for option in field["options"]}
            unknown = [item for item in values if item not in options]
            if unknown:
                raise SkillValidationError(f"{field['label']} contains an unknown selection.")
            return "; ".join(options[item] for item in values)
        if not isinstance(value, str):
            raise SkillValidationError(f"{field['label']} must be text.")
        return value.strip()

    @staticmethod
    def _is_empty(value):
        return value is None or value == "" or value == []

    @staticmethod
    def _require_string(value, field, location):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise SkillValidationError(f"{location}: {field} must be a non-empty string")

    @staticmethod
    def _reject_unknown_fields(value, allowed, location):
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise SkillValidationError(f"{location}: unknown field(s): {', '.join(unknown)}")


def main():
    parser = argparse.ArgumentParser(description="Validate ASCS Reviewer JSON skill files.")
    parser.add_argument("directory", nargs="?", default=Path(__file__).resolve().parent / "skills")
    args = parser.parse_args()
    try:
        store = SkillStore(args.directory).load()
    except SkillValidationError as exc:
        print(f"Skill validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Validated {len(store.list_skills())} skill file(s) using schema version {SCHEMA_VERSION}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
