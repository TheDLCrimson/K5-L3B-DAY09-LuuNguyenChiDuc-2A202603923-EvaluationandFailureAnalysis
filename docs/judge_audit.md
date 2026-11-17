# Judge audit

Run on 18/11/2026 in replay mode (the judge verdicts are stored in the CSV, no model call, no key).
FAIL is the positive class: a judge is useful when it finds failures.

```bash
cd src
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 5
python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 5
```

| Criterion | n | tp / fp / fn / tn | kappa | Precision | Recall | Passes floors (kappa >= 0.6, P >= 0.8, R >= 0.7)? | Decision |
|---|---|---|---|---|---|---|---|
| tone_ok | 100 | 24 / 4 / 6 / 66 | 0.757 | 0.857 | 0.800 | yes, all three | use |
| helpful | 100 | 9 / 0 / 21 / 70 | 0.375 | 1.000 | 0.300 | no: kappa and recall fail | do not use as a gate |

Rogan-Gladen correction of the observed failure rate (sensitivity from recall, specificity from tn / (tn + fp)):

| Criterion | Observed fail rate | Corrected | Humans actually marked FAIL |
|---|---|---|---|
| tone_ok | 0.28 | 0.30 | 0.30 |
| helpful | 0.09 | 0.30 | 0.30 |

The helpful judge reports 9% failures when humans find 30%.
Rogan-Gladen recovers 30%, but only because the specificity is a perfect 1.0 here.
That is a repair of a number, not a reason to keep gating on a judge that misses 70% of the failures it is supposed to find.

## 6 manual audits of disagreements

| # | Case | Judge says | Human says | Who is right? | Rubric fix |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS (friendly) | FAIL | Human. Customer service uses the formal "Dạ" and "anh/chị" register; "em ... nha" talks to the customer as a peer. | Name the register in the rubric and list casual particles ("nha", "nhé", "bạn ơi") as failures. The same fix covers H-017 ("bạn ơi ... rồi nha"). |
| 2 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3-5 ngày ạ." | FAIL (no apology) | PASS | Human. A successful refund is complete and polite without an apology. | Require an apology only when the claim was denied or the delivery was late; never for a plain successful refund. |
| 3 | H-051 "Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ." | FAIL (English word) | PASS | Human. LogiX customer service allows "refund" (the CSV note says so). | Add a short allow-list of English terms to the rubric, so the judge stops penalising them. |
| 4 | H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ cho đơn O-233 ạ." | FAIL | PASS | Human. A doubled "Dạ" is a typing slip, not a tone problem. | State that tone_ok judges register only and ignores typos. Typos get their own check if we ever need one. |
| 5 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ." | FAIL | PASS | Judge. The CSV note says the human misread the ticket, and the label should be corrected. | Fix the human label (the CSV itself is left as given). With this row flipped the judge's tone numbers improve, so the published kappa is slightly pessimistic. |
| 6 | H-063 "Dạ, LogiX đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | Human. The reply promises more money than the system outcome shows ("sẽ hoàn thêm"). | Do not fix this in the tone rubric. Treat it as FM-08 (reply vs ledger) and grade it with code, not with a tone judge. |

Further rows from the same file that follow the same patterns: H-017 (as case 1), H-029 (a command, "không cần nhắn thêm", which the judge read only as "Dạ, vui lòng"), H-070 (emoji in a complaint reply) and H-094 (Vietnamese without diacritics from machine translation).
In every one of those the human is right and the judge is too lenient.

## Why the helpful judge cannot be the gate

Of the 30 replies that humans marked FAIL, the judge caught 9 and missed 21.
Splitting the 30 by cause:

| Cause of the human FAIL | Rows | Judge caught | Judge missed |
|---|---|---|---|
| Reply states an amount that differs from the ledger (the CSV note says "ledger ghi ...") | 18 | 0 | 18 |
| "Ok bạn, đơn ... xử lý rồi nhé" (curt, no amount, no explanation) | 3 | 0 | 3 |
| Empty or curt replies (thanks only, "Bạn gửi lại thông tin đi", a refusal with no reason) | 9 | 9 | 0 |

- The judge catches every reply that is obviously unhelpful and **none** of the 18 replies that state a wrong amount.
- Those 18 are exactly FM-08 `misreport`: fluent, polite, and wrong.
  The judge reads text; the amount is only right or wrong against the ledger, which it never sees.
- Three misses (HL-015, HL-062, HL-100) are one-line replies "Dạ, LogiX đã hoàn 55.000đ cho đơn ... ạ." whose only fault is the amount.
  Longer misses (HL-016, HL-028, HL-035 and others) pad the same wrong amount with repeated apologies, so the judge also rewards length.
- A gate must not let a wrong refund amount through, and here recall on that class is 0 of 18.
  That is enough on its own to reject the judge, independent of the kappa floor.

Decision: money is graded by code (`refund_amount_correct` and the new FM-08 metric from M3).
The tone judge stays as a non-blocking quality signal, after the rubric fixes above are applied.

## Conclusion

- Rejected: `helpful`. Confusion matrix 9 / 0 / 21 / 70, recall 0.30 against a floor of 0.70, kappa 0.375 against 0.6, and 0 of 18 amount mismatches found.
- Kept: `tone_ok`. Kappa 0.757, precision 0.857, recall 0.8, all above the floors.
  The 10 disagreements are mostly rubric gaps (register, apology, English terms, typos), so they are fixable by tightening the rubric, not by changing the judge.
- Remaining risk: the judge was only checked on public replay data that is already known.
  We have no fresh human labels, so there is no true held-out set.
  With 100 items and 30 failures the recall estimate is wide: 24 of 30 could easily be 20 or 28 on another sample.
- `kappa` is reported as undefined (and counted as a failure) for a constant judge, so a judge that says PASS to everything can never pass calibration on a technicality.
