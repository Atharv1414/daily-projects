| Model | Trainable params | Train time | Exact match (seen) | Exact match (unseen) | Category macro-F1 (unseen) | Vulnerable recall (unseen) | High-urgency recall (unseen) |
|---|---:|---:|---:|---:|---:|---:|---:|
| majority | – | 0.0 s | 4.5% | 2.1% | 0.027 | 0.0% | 0.0% |
| keyword rules | – | 0.0 s | 44.7% | 16.3% | 0.625 | 6.5% | 46.1% |
| TF-IDF + logistic regression | – | 2.5 s | 98.1% | 21.0% | 0.425 | 24.6% | 50.0% |
| LoRA, pre-trained without unlabelled traffic | 18,048 | 31.5 s | 90.5% | 19.6% | 0.342 | 55.8% | 49.7% |
| Full, pre-trained without unlabelled traffic | 932,224 | 32.9 s | 99.4% | 27.5% | 0.462 | 27.7% | 52.4% |
| Head only (label rows) | 1,664 | 25.6 s | 56.8% | 18.0% | 0.393 | 42.3% | 56.1% |
| LoRA r=8 (q, v) + label rows | 18,048 | 30.7 s | 92.2% | 31.4% | 0.597 | 85.4% | 52.4% |
| Full fine-tune | 932,224 | 30.3 s | 99.7% | 40.1% | 0.597 | 80.0% | 63.9% |
| LoRA merged, int8 | none (post-training) | – | 92.3% | 31.6% | 0.597 | 85.4% | 52.1% |
