# Agent run 20260929-193240-agent-b2e7e0

- **Issues:** 100; stop reasons: submitted 100
- **Forced final answers:** max_steps 52, max_tool_calls 1
- **Steps per issue:** mean 9.3, p95 12
- **Tool calls per issue:** mean 9.4, max 15
- **Skill load rate:** 1% of issues called `load_skill`
- **Validation errors:** 0 issues; compactions: 0
- **Tokens per issue:** 69,440 in, 1,951 out (1,378 reasoning)
- **Cost per issue:** $0.00724; latency p50 164 s, p95 641 s

| tool | calls | per issue | issues using it | errors |
|---|---|---|---|---|
| get_codeowners | 10 | 0.10 | 6 | 0 |
| get_issue | 95 | 0.95 | 67 | 9 |
| list_components | 4 | 0.04 | 4 | 0 |
| load_skill | 1 | 0.01 | 1 | 0 |
| read_skill_file | 11 | 0.11 | 8 | 0 |
| search_code | 430 | 4.30 | 56 | 14 |
| search_similar_issues | 385 | 3.85 | 100 | 0 |
