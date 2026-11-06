# Deneysel sonuçlar

Bu rapor, yerelde yeniden üretilebilen yazılım ve retrieval deneylerini özetler.
Hiçbir sonuç klinik validasyon, hasta uygunluğu veya tıbbi güvenlik garantisi
değildir.

## Veri ve yöntem

TREC Clinical Trials 2021 ve 2022 qrels'lerinden 25 topic seçildi: 2021'in ilk
9 topic'i ve 2021'de vaka metninde meme kanserinden söz eden altı topic (25, 39,
49, 50, 57, 61), ayrıca 2022'nin ilk 10 topic'i. Seçilen 2021 topic'leri 7.029,
2022 topic'leri 7.215 yargı kaydı içerir; toplamda 14.244 yargı ve iki yıl
arasında 12.412 benzersiz çalışma belgesi vardır. Bu örneklemdeki altı meme
kanseri topic'i ayrı da raporlanmıştır. Kalan topic'ler farklı hastalıkları
kapsar.

Her iki yılın yargılanmış belgeleri 27 Nisan 2021 ClinicalTrials snapshot'ından
alınmıştır. Topic metinleri, qrels ve belgeler yalnızca seçilen topic'ler için
hazırlanır; tam korpus indeksi kurulmaz.

Karşılaştırılan sistemler:

- **B1:** Topic metninde BM25 keyword araması, terim genişletme yok.
- **Sözlük:** Projenin TR↔EN terim sözlüğüyle genişletilmiş topic üzerinde BM25.
- **Final:** B1'in ilk 100 qrels-yargılı adayı, proje kriter değerlendiricisiyle
  yeniden sıralanır.
- **B0:** Arama aracı veya çalışma kaydı verilmeyen yerel Qwen3 1.7B, yalnızca
  topic anlatısından en fazla 10 NCT kimliği önermeye çalışır.

P@10 için yalnızca qrels etiketi `2` (eligible) ilgili kabul edilir. nDCG@10'da
qrels etiketleri 0/1/2 kazanç olarak kullanılır. Tablolar topic başına
metriklerin makro ortalamasıdır.

## Sonuçlar

| Topic kümesi | Topic sayısı | Sistem | P@10 | nDCG@10 |
|---|---:|---|---:|---:|
| Tümü | 25 | B1 | 0.1120 | 0.2105 |
| Tümü | 25 | Sözlük | 0.1160 | 0.2134 |
| Tümü | 25 | Final | 0.1640 | 0.2747 |
| Tümü | 25 | E5 hybrid | 0.1800 | 0.3388 |
| Tümü | 25 | B0 tool'suz Qwen3 1.7B | 0.0000 | 0.0000 |
| 2021 | 15 | B1 | 0.0800 | 0.1904 |
| 2021 | 15 | Sözlük | 0.0800 | 0.1916 |
| 2021 | 15 | Final | 0.1467 | 0.2832 |
| 2021 | 15 | E5 hybrid | 0.1333 | 0.3121 |
| 2022 | 10 | B1 | 0.1600 | 0.2407 |
| 2022 | 10 | Sözlük | 0.1700 | 0.2460 |
| 2022 | 10 | Final | 0.1900 | 0.2620 |
| 2022 | 10 | E5 hybrid | 0.2500 | 0.3790 |
| Meme kanseri topic'leri | 6 | B1 | 0.0833 | 0.1499 |
| Meme kanseri topic'leri | 6 | Sözlük | 0.1000 | 0.1803 |
| Meme kanseri topic'leri | 6 | Final | 0.1333 | 0.1960 |
| Meme kanseri topic'leri | 6 | E5 hybrid | 0.1333 | 0.2892 |
| Meme kanseri topic'leri | 6 | B0 tool'suz Qwen3 1.7B | 0.0000 | 0.0000 |

E5 hybrid, bu kapalı korpusta genel 25 topic'te B1'e göre P@10'u 0.0680 ve
nDCG@10'u 0.1283 artırdı; Final'e göre de sırasıyla 0.0160 ve 0.0642 daha
yüksek ölçüldü. Altı meme kanseri topic'inde E5'in P@10'u B1'den 0.0500,
nDCG@10'u 0.1393 daha yüksek; Final ile P@10 eşit, nDCG@10 ise 0.0933 daha
yüksek çıktı. Sözlük genişletme genel sette daha küçük bir artış gösterdi.
Sonuçlar her topic'te iyileşme anlamına gelmez: meme topic'i 2021:25'te E5'in
nDCG@10'u B1'den düşükken Final daha yüksektir. Altı örnekli alt küme güçlü
genelleme iddiası için yeterli değildir. E5 ölçümü yerel CPU'da yaklaşık
50 dakika sürdü.

## NCT kimlik doğrulaması

| Sistem | Topic run'larındaki NCT önerisi | Kaynakta bulunmayan / uydurma | Oran |
|---|---:|---:|---:|
| B0 tool'suz Qwen3 1.7B | 52 | 37 | %71,15 |
| B1 BM25 | 2.500 | 0 | %0 |
| Sözlük BM25 | 2.500 | 0 | %0 |
| Final | 2.500 | 0 | %0 |
| E5 hybrid | 2.500 | 0 | %0 |

B1, Sözlük, Final ve E5'in kimlikleri TREC snapshot'ındaki, XML'den NCT
kimliği doğrulanarak çıkarılmış çalışma kayıtlarından gelir. Bu nedenle bu
kapalı-korpus ölçümünde kaynak dışı NCT oranı sıfırdır. B0'ın 52 önerisi
ClinicalTrials.gov API v2 ile 5 Kasım 2026'da kontrol edildi; 37 öneri kimliği
API'de bulunmadı. Oran, öneri örnekleri içindeki bulunamayan kimliklerin
payıdır; aynı kimliğin tekrarlı önerileri ayrı öneri olarak sayılır. Bu canlı
API kontrolü, TREC snapshot doğrulamasından farklı bir kaynaktır ve tarih
değiştikçe yeniden ölçülmelidir. B0'ın P@10/nDCG@10 sonuçları aynı kapalı
qrels korpusunda hesaplandı; canlı ClinicalTrials sıralaması değildir.

## LLM-as-judge

Yerel Qwen3 1.7B, 10 sentetik örneğin kriter alıntısı tutarlılığı ve güvenli
dilini 1–5 arasında puanladı. Kullanıcı her iki boyutta da 10 örneğe 5/5 insan
puanı verdi. Qwen3 1.7B'nin MAE'si alıntı tutarlılığında **0,50**, güvenli
dilde **0,00** oldu. Bu değerler yalnızca bu küçük sentetik set ve verilen
puanlama için geçerlidir; bağımsız uzmanlar arası uyum, genellenebilir
kalibrasyon veya klinik kalite kanıtı değildir. İnsan puanlarıyla birlikte
model tahminleri ve çalıştırma ayrıntıları yerel judge raporundadır.

## Sınırlılıklar

- Bu, yargılanmış belgelerle sınırlı kapalı-korpus retrieval ablation'ıdır.
  Yargılanmamış ClinicalTrials kayıtları aday kümesinde yoktur.
- Final, yalnızca B1'in ilk 100 adayı içinde yeniden sıralama yapar; bağımsız
  tam-korpus retriever veya canlı ClinicalTrials.gov sıralaması değildir.
- Altı meme kanseri topic'i küçük bir örneklemdir. Kriter değerlendiricisinin
  TREC qrels'ine göre başarımı klinik uygunluk doğruluğu olarak yorumlanamaz.
- TREC sonuçları uygulamanın canlı API akışını, hekim kararını, prospektif
  performansı veya gerçek hasta verisini değerlendirmez.
- E5, `intfloat/multilingual-e5-small` ile yerel CPU'da çalıştırıldı. BAAI
  reranker ölçülmedi.
- B0 sonuçları tek bir küçük yerel model ve 25 topic'e dayanır; sıfır
  retrieval metriği, genel LLM performansı hakkında sonuç vermez.
- Judge tahminleri çalıştırıldı; MAE kalibrasyonu için en az 10 örneğin her
  birinde iki boyut için insan puanı gerekir. Bu puanlar otomatik doldurulamaz.

## Yeniden üretme

TREC dosyalarını hazırlamak ve baseline'ları çalıştırmak için:

```powershell
python scripts\prepare_trec_eval.py
python scripts\run_trec_baselines.py --topics data\eval\trec_2021.json data\eval\trec_2022.json --output reports\trec_baseline_comparison.json
python scripts\run_trec_baselines.py --topics data\eval\trec_2021.json data\eval\trec_2022.json --enable-embeddings --output reports\trec_e5_comparison.json
```

`data/eval/` ve `reports/` yerel, yeniden üretilebilir çıktılardır; rapordaki
özet metrikler bu belgede kalıcı olarak tutulur. B0 koşusu için ayrıca yerel
Ollama ve bir model gerekir; çalıştırma komutu `README.md` içindedir. Kalan
sentetik kriter ve güvenlik ölçümleri ile bunların yorum sınırları da
`README.md` içindedir.
