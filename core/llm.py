import json
import requests


class LLMConnectionError(Exception):
    pass


class LLMClient:
    def __init__(self, config: dict):
        self.endpoint = config["endpoint"].rstrip("/")
        self.model = config["model"]
        self.timeout = config["timeout_seconds"]
        self.system_prompt_join = config["system_prompt_join"]
        self.system_prompt_rule = config["system_prompt_rule"]

    def _call(self, system_prompt: str, user_message: str) -> str:
        payload = {
            "model": self.model,
            "prompt": user_message,
            "system": system_prompt,
            "stream": False,
        }
        try:
            response = requests.post(
                f"{self.endpoint}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise LLMConnectionError(
                f"Cannot reach Ollama at {self.endpoint}. Please ensure Ollama is running."
            )
        except requests.exceptions.Timeout:
            raise LLMConnectionError(
                f"Ollama request timed out after {self.timeout}s. Try increasing timeout_seconds in config."
            )
        data = response.json()
        sql = data.get("response", "").strip()
        # Strip markdown fences if the model included them despite instructions
        if sql.startswith("```"):
            lines = sql.split("\n")
            sql = "\n".join(line for line in lines if not line.startswith("```")).strip()
        return sql

    def translate_join(self, nl_instruction: str, table_names: list[str], col_hints: dict[str, list[str]]) -> str:
        schema_info = "\n".join(
            f"Table '{t}': columns = {', '.join(col_hints.get(t, []))}"
            for t in table_names
        )
        user_message = f"{schema_info}\n\nInstruction: {nl_instruction}"
        return self._call(self.system_prompt_join, user_message)

    def translate_rule(self, nl_rule: str, col_hints: list[str]) -> str:
        schema_info = f"Table 'joined_table': columns = {', '.join(col_hints)}"
        user_message = f"{schema_info}\n\nRule: {nl_rule}"
        return self._call(self.system_prompt_rule, user_message)
