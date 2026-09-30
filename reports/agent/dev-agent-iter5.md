# Agent run 20260930-000255-agent-cf734a

- **Issues:** 100; stop reasons: no_answer 1, submitted 99
- **Forced final answers:** max_steps 44, max_tool_calls 4
- **Steps per issue:** mean 8.7, p95 12
- **Tool calls per issue:** mean 9.1, max 15
- **Skill load rate:** 1% of issues called `load_skill`
- **Validation errors:** 0 issues; compactions: 0
- **Tokens per issue:** 61,407 in, 2,052 out (1,445 reasoning)
- **Cost per issue:** $0.00645; latency p50 99 s, p95 260 s

| failure category | failures |
|---|---|
| topic/OS over-labeling | 42 |
| code-location confusion | 31 |
| type-label error | 20 |
| correct evidence ignored | 14 |
| search process failure | 13 |
| duplicate retrieval error | 13 |
| needs-info over-flagging | 6 |
| repository guidance unused | 2 |
| hallucinated file or label | 1 |

| tool | calls | per issue | issues using it | errors |
|---|---|---|---|---|
| get_codeowners | 9 | 0.09 | 8 | 0 |
| get_issue | 101 | 1.01 | 70 | 7 |
| list_components | 2 | 0.02 | 2 | 0 |
| load_skill | 1 | 0.01 | 1 | 0 |
| read_skill_file | 13 | 0.13 | 11 | 0 |
| search_code | 435 | 4.35 | 59 | 11 |
| search_similar_issues | 345 | 3.45 | 100 | 0 |
