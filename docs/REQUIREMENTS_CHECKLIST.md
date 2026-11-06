# Yönerge ve görsel kontrol listesi

Durum, kaynak yönerge ve paylaşılan mimari/özellik görselleriyle kod ve testler
karşılaştırılarak yazılmıştır. "Dış adım" yerel kodla tamamlanamayacak yayın,
model veya veri gereksinimini ifade eder; ölçülmeyen sonuçlar tamamlandı diye
sunulmaz.

## Önerilen seviye

| İstek | Durum | Kanıt / kalan sınır |
|---|---|---|
| Orkestratör + Intake/PII, Profile, Search, Eligibility, Report, Safety Critic | Tamam | `trialmatch/agents.py`; testlerde her rolün akışı |
| Kendi ClinicalTrials MCP server + MCP client | Tamam | `trialmatch/mcp_server.py`, `trialmatch/mcp_client.py`; stdio alt-süreç |
| Kriterleri chunk etme ve hybrid retrieval | Tamam | Her kriter ayrı chunk; sözlük/lexical + isteğe bağlı E5; hiçbir kriter atlanmaz |
| E5 ile aynı model kullanarak yerel indeks üretme | Tamam (isteğe bağlı) | `data/cache/criteria-index.json`; model adı indekste tutulur. Hafif kurulumda E5 kapalı |
| BAAI reranker | Tamam (isteğe bağlı kod) | `TRIALMATCH_RERANKER`; model indirme/RAM ihtiyacı nedeniyle varsayılan kapalı |
| Chroma/Qdrant/LanceDB | Kullanılmıyor | Yerel JSON vektör indeksi daha hafif ve yeterli; ek veritabanı kurulumuna gerek yok |
| TREC P@10/nDCG@10, B0/B1/Final ve NCT oranı | 25 topic'te ölçüldü | B0 Qwen3 1.7B 0.0000/0.0000; B1 0.1120/0.2105; Final 0.1640/0.2747. B0'ın 52 NCT önerisinin 37'si (%71,15) 2026-11-05 tarihli canlı API kontrolünde bulunmadı. Altı meme topic'i ve yöntem sınırları `docs/EVALUATION_RESULTS.md` içinde |
| LLM-as-judge ve en az 10 insan puanıyla kalibrasyon | 10 sentetik örnek puanlandı ve kullanıcı puanları girildi | İnsan puanları her iki boyutta da 5/5; Qwen3 1.7B MAE: alıntı tutarlılığı 0,50, güvenli dil 0,00. Küçük sentetik örneklem ve tek puanlayıcı; uzmanlar arası uyum/klinik doğrulama değildir |
| En az 5 hata analizi | Tamam | `docs/ERROR_ANALYSIS.md`; sentetik testler ve sınıflandırıcı hata örnekleri |
| PII içermeyen trace, adım gecikmesi/token/maliyet | Tamam | `data/cache/traces.jsonl`; isteğe bağlı Phoenix OTLP aktarımı. Token/maliyet 0, üretim akışında LLM yok |
| Streamlit arayüzü | Tamam | Profil gözden geçirme, kriter tablosu, rapor onayı, kalıcı uyarı |
| Herkese açık demo yayını | Dış adım | Hesap, public repo ve yayın onayı gerekir; bu repo henüz yayınlanmadı |

## İleri seviye

| İstek | Durum | Kanıt / kalan sınır |
|---|---|---|
| TR↔EN sözlük ve E5, katkı ölçümü | Sözlük ve E5 ölçüldü | Genel kümede E5 nDCG@10 0.3388, B1 0.2105; altı meme topic'inde E5 0.2892, B1 0.1499. Sonuçlar kapalı-korpus retrieval karşılaştırmasıdır |
| Hastalık-biyobelirteç-ilaç bilgi grafiği | Tamam | `data/clinical_knowledge_graph.json`; prior trastuzumab → anti-HER2 kriteri testi var. HER2 tek başına tedavi kanıtı sayılmaz |
| 50 km mesafe filtresi ve en yakın merkez sıralaması | Tamam (tanımlı şehirlerle) | ClinicalTrials `geoPoint`; kullanıcı konum koordinatı saklanmaz. Bilinmeyen şehirde mesafe iddia edilmez |
| Sade dil bilgilendirmesi + okunabilirlik ölçümü | Tamam | Sade Türkçe özet, yaklaşık Ateşman puanı ve ölçümün sınırlılığı UI'da gösterilir |
| Küçük sınıflandırıcı ve LLM maliyet/doğruluk karşılaştırması | Kısmi/deneysel | Naive Bayes eğitimi ve vaka-bazlı CV tamam. 26,7% sonuç nedeniyle üretime bağlanmadı; yerel Ollama karşılaştırması henüz çalıştırılmadı. Önceden eğitilmiş sinir ağı fine-tune edilmedi |

## Temel yönerge ve teslim

| İstek | Durum | Kanıt / kalan sınır |
|---|---|---|
| 5 sentetik vaka, en az 25 kriter etiketi ve ≥30% UNKNOWN | Tamam | `data/synthetic_cases.json`, `data/golden_criteria.json` |
| PII, kapsam dışı ret, injection setleri (her biri ≥10) | Tamam | `data/security_tests.json` ve parametreli pytest |
| Hasta profil şeması; bulunmayan alanı uydurmama | Tamam | Pydantic şeması, kaynak aralıkları ve testler |
| Kriter alıntısı, kanıt, UNKNOWN ve NCT doğrulama | Tamam | MCP `get_trial`, Safety Critic ve birim testleri |
| 25 TREC topic üzerinde retrieval sonucu | B0/B1/sözlük/Final/E5 ölçüldü | Makro sonuçlar ve kapalı-korpus/canlı API farkı `docs/EVALUATION_RESULTS.md` içinde; klinik validasyon değildir |
| Teknik yazı | Taslak var | `docs/TECHNICAL_ARTICLE.md`; sonuçlar ve yayın platformu gerektirir, yayımlanmadı |
