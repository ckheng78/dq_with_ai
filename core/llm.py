import re
import time
import requests


class LLMConnectionError(Exception):
    pass


def _extract_sql(text: str) -> str | None:
    text = re.sub(r"```sql", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```", "", text)
    m = re.search(r"\bSELECT\b", text, re.IGNORECASE)
    if not m:
        return None
    text = text[m.start():]
    semi = text.find(";")
    if semi != -1:
        text = text[:semi]
    if len(re.findall(r"\bSELECT\b", text, re.IGNORECASE)) > 1:
        return None
    # REGEX_LIKE does not exist in DuckDB; correct to REGEXP_MATCHES.
    text = re.sub(r"\bREGEX_LIKE\b", "REGEXP_MATCHES", text, flags=re.IGNORECASE)
    return text.strip() or None


class LLMClient:
    def __init__(self, config: dict):
        self.endpoint = config["endpoint"].rstrip("/")
        self.model = config["model"]
        self.timeout = config["timeout_seconds"]
        self.system_prompt_rule = config["system_prompt_rule"]
        self.options = {"temperature": 0, "num_predict": 200, **config.get("options", {})}

    def _call(self, system_prompt: str, user_message: str) -> str | None:
        url = f"{self.endpoint}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "options": {**self.options, "stop": [";", "```", "\n\n"]},
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
        raw = data["message"]["content"].strip()
        print(f"[LLM] raw response=\n{raw}")
        sql = _extract_sql(raw)
        print(f"[LLM] extracted sql=\n{sql}")
        return sql

    def _validate_sql_columns(self, sql: str, valid_columns: list[str]) -> bool:
        valid_set = {c.upper() for c in valid_columns}
        candidates = re.findall(r'\bPA\w+\b', sql, re.IGNORECASE)
        for candidate in candidates:
            if candidate.upper() not in valid_set:
                print(f"[LLM] Column validation rejected: {candidate!r} not in valid columns")
                return False
        return True

    def translate_rule(self, nl_rule: str, col_hints: list[str]) -> str:
        schema_info = f"Table 'joined_table': columns = {', '.join(col_hints)}"
        user_message = f"{schema_info}\n\nRule: {nl_rule}"
        max_tries = 5
        for attempt in range(1, max_tries + 1):
            sql = self._call(self.system_prompt_rule, user_message)
            if not sql or not sql.strip().upper().startswith("SELECT"):
                print(f"[LLM] Attempt {attempt}/{max_tries}: no valid SELECT — got: {str(sql)[:120]!r}")
                if attempt < max_tries:
                    time.sleep(5)
                continue
            if not self._validate_sql_columns(sql, col_hints):
                print(f"[LLM] Attempt {attempt}/{max_tries}: column validation failed")
                if attempt < max_tries:
                    time.sleep(5)
                continue
            return sql
        raise LLMConnectionError(
            f"LLM failed to produce a valid SELECT statement after {max_tries} attempts.\n"
            "Please rephrase your rule description and try again."
        )
