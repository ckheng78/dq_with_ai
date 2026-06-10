import re
import requests


class LLMConnectionError(Exception):
    pass


def _extract_sql(text: str) -> str:
    # If model wrapped in code fences, pull content out first
    fence_match = re.search(r"```(?:sql)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()

    # Find the first SQL keyword and take everything from there
    sql_start = re.search(r"\b(SELECT|WITH|INSERT|UPDATE|DELETE)\b", text, re.IGNORECASE)
    if sql_start:
        text = text[sql_start.start():]

    # Truncate at the last semicolon to drop trailing commentary
    last_semi = text.rfind(";")
    if last_semi != -1:
        text = text[: last_semi + 1]

    return text.strip()


class LLMClient:
    def __init__(self, config: dict):
        self.endpoint = config["endpoint"].rstrip("/")
        self.model = config["model"]
        self.timeout = config["timeout_seconds"]
        self.system_prompt_join = config["system_prompt_join"]
        self.system_prompt_rule = config["system_prompt_rule"]

    def _call(self, system_prompt: str, user_message: str) -> str:
        url = f"{self.endpoint}/api/generate"
        payload = {
            "model": self.model,
            "prompt": user_message,
            "system": system_prompt,
            "stream": False,
        }
        print(f"[LLM] POST {url}")
        print(f"[LLM] model={self.model!r}  timeout={self.timeout}s")
        print(f"[LLM] system_prompt=\n{system_prompt}")
        print(f"[LLM] user_message=\n{user_message}")
        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
            print(f"[LLM] response status={response.status_code}")
            print(f"[LLM] response body=\n{response.text[:2000]}")
            response.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            print(f"[LLM] ConnectionError: {e}")
            raise LLMConnectionError(
                f"Cannot reach Ollama at {self.endpoint}. Please ensure Ollama is running."
            )
        except requests.exceptions.Timeout:
            print(f"[LLM] Request timed out after {self.timeout}s")
            raise LLMConnectionError(
                f"Ollama request timed out after {self.timeout}s. Try increasing timeout_seconds in config."
            )
        except requests.exceptions.HTTPError as e:
            print(f"[LLM] HTTPError: {e}")
            raise
        data = response.json()
        raw = data.get("response", "").strip()
        print(f"[LLM] raw response=\n{raw}")
        sql = _extract_sql(raw)
        print(f"[LLM] extracted sql=\n{sql}")
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
