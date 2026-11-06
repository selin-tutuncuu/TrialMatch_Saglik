# Taslak: Klinik çalışma ön değerlendirmesinde kanıt ve belirsizlik

> Yayın taslağıdır; teknik sonuçların tamamı ölçülmeden yayınlanmamalıdır.
> Gerçek hasta verisi, doğrulanmamış performans iddiası veya klinik tavsiye
> içermez.

## Sorun

Klinik araştırma koordinatörü için uygunluk metinleri uzun, serbest metin ve
çoğu zaman İngilizcedir. Bu prototip meme kanserini yalnızca sentetik Türkçe
vakalar ve terim sözlüğü için odak seçer; çalışma arama hattı hastalıktan
bağımsızdır.

## Tasarım

PII taraması tüm diğer adımlardan önce yapılır. Klinik kriterleri madde madde
ayıklanır; yaş ve cinsiyet gibi yapılandırılmış alanlar deterministik kontrol
edilir. Her karar orijinal kriter alıntısını ve anonim özetteki kanıtı taşır.
Metinde olmayan bilgi `UNKNOWN` kalır. MCP üzerinden ClinicalTrials.gov araması
yapılır; ayrı Safety Critic NCT kimliklerini, kanıtı ve dili doğrular.

Önerilen mimari altı görevli modüle ayrılmıştır. ClinicalTrials MCP server
ayrı stdio sürecinde çalışır. İsteğe bağlı E5 embedding'leri aynı modelle
indekslenip sorgulanır; kriter chunk'ları atlanmadan değerlendirilir.
İleri özellikler arasında terim bilgi grafiği, şehir merkezine göre geo
filtreleme/mesafe sıralaması ve yaklaşık Ateşman okunabilirlik tahmini vardır.

## Sınırlar

Bu prototip LLM kullanmaz ve hasta başına sonuç verimliliği veya klinik
doğruluk iddiası taşımaz. Sentetik golden set yazılım testidir; klinik altın
standart değildir. PII regex'leri serbest metindeki tüm tanımlayıcıları
yakalayamaz; bu nedenle gerçek veri kesinlikle girilmemelidir. Son karar daima
hekim/çalışma ekibinindir.

## Yazılım deneyleri ve kalan değerlendirmeler

- Kural tabanlı evaluator 30/30 golden çiftte doğruydu; aynı örnekler kural
  geliştirmesinde kullanıldığı için bu in-sample test klinik/bağımsız başarı
  iddiası değildir.
- 30 örnek üzerinde vaka-bazlı leave-one-case-out Naive Bayes doğruluğu
  8/30 (%26,7) oldu. Bu model raporlama yoluna eklenmedi; beş hata ve güvenli
  fallback [hata analizinde](./ERROR_ANALYSIS.md) açıklanmıştır.
- TREC 2021/2022'nin seçilen 25 topic'i üzerinde BM25 B1, TR↔EN sözlük
  genişletme ve kriter tabanlı Final yeniden sıralaması çalıştırıldı. Final
  makro nDCG@10'u B1'e göre 0.2105'ten 0.2747'ye çıkardı; altı meme kanseri
  topic'inde 0.1499'dan 0.1960'ya çıktı. Bu kapalı, qrels-yargılı retrieval
  ablation'ıdır; uçtan uca klinik değerlendirme değildir. Yöntem ve tam
  sonuçlar [deney raporunda](./EVALUATION_RESULTS.md) yer alır.
- `intfloat/multilingual-e5-small` E5 hybrid, 25 topic'te makro nDCG@10'u
  0.3388, meme kanseri alt kümesinde 0.2892 verdi. Alt kümede P@10 0.1333
  oldu; küçük örneklem ve kapalı-korpus sınırı nedeniyle klinik performans
  şeklinde yorumlanmamalıdır.
- Araçsız yerel Qwen3 1.7B, 25 TREC topic'te P@10/nDCG@10 için 0.0000/0.0000
  verdi. Üretilen 52 NCT önerisinin 37'si 2026-11-05 tarihinde canlı
  ClinicalTrials.gov API v2 tarafından bulunamadı (%71,15). Tek bir küçük
  model ve sentetik benchmark'a dayanan bu sonuç genellenemez.
- Aynı yerel model 10 sentetik örneği LLM-as-judge olarak puanladı; kullanıcı
  tüm örneklere iki boyutta da 5/5 insan puanı verdi. MAE alıntı tutarlılığında
  0,50, güvenli dilde 0,00 oldu. Bu tek puanlayıcılı küçük sentetik ölçüm,
  bağımsız değerlendirme veya klinik kanıt değildir.
- Bağımsız klinik uzmanların etiketleri/uyuşması ve prospektif validasyon yoktur.

Test paketi yazılım regression doğrulamasıdır; klinik performans kanıtı değildir.
Bağımsız uzman değerlendirmesi, puanlayıcılar arası uyum ve prospektif
validasyon halen eksiktir.
