# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi bạn 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `<shape> <claim>@<seed>`, run ID trong report |
| Triệu chứng | Grader nào fail; reply nói gì so với ledger ghi gì |
| Bước sai đầu tiên | Số thứ tự event + kind + trích payload (≤1 dòng) |
| Vì sao là bước *đầu tiên* | Các bước trước đó đúng ra sao (dẫn số event) |
| Failure mode | Mã FM-xx trong `docs/failure_taxonomy.md` |
| Đối chứng | Cùng claim@seed trên shape `fixed`: bước đó khác thế nào |
| Regression test | Tên test + grader/assert nào bắt được; đã thấy fail trên variant lỗi và pass trên `fixed` chưa |
| Chưa chắc chắn | Điều trace không chứng minh được |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.

## My case: C-002@11 on seeded_regression

| Field | Content |
|---|---|
| Trial | `seeded_regression C-002@11`, trace run `R-seeded_regression-C-002-s11` (the report `run_id` is added once `reports/eval_seeded_regression.json` exists at M4) |
| Symptom | The Lab 8 grader fails with `status resolved != denied`. The reply says "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202." and the ledger agrees (refund_vnd 20000, refund_count 1), but the label is a denial with refund 0. |
| First wrong step | Event 3 `model_override {"delay_days": 5}`: the agent replaced the order's delay by the number in the ticket. |
| Why it is the *first* step | Event 2 `investigator` read order O-202 from the database correctly (delay 2 days, a delay that earns no refund). Event 1 `handoff` only scopes the tools. Events 4 to 6 (`quote` 20.000đ, `refund_history`, `reply`) all follow from the overridden delay. |
| Failure mode | FM-03 ticket_trust |
| Control | `fixed` on the same claim and seed has no `model_override`; event 3 `quote` is `{"amount_vnd": 0, "reason": "no_entitlement"}` and event 4 `reply` is the denial text. Ledger refund 0, grader PASS. |
| Regression test | Planned for M3: `DbFactKept` flags the `model_override` event, and `RefundAmountCorrect` flags ledger 20000 against label 0. It is not yet shown failing on `seeded_regression` and passing on `fixed`, because both graders still raise `NotImplementedError`. |
| Not certain | The trace shows that the override happened, not why. In `variant_agent` it is a bug switch, so the trace cannot tell whether a real model would have been persuaded by the ticket wording or by a parsing slip. |

Commands used:

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11
```
