# PMR Wallet: спецификация

Non-custodial мультичейн-кошелёк с P2P-маркетплейсом (iOS, Android, backend).

> В файле собраны разделы, затронутые ревизией «BSC + Security & Validation».
> Разделы базовой спецификации, которые не менялись, в репозиторий пока не добавлены.
> Пункты с пометкой **⚠️ R‑N** ссылаются на [замечания ревью](#замечания-ревью) в конце документа.

## Changelog

- **BSC (BEP20 USDT)** добавлен как четвёртая обязательная сеть: деривация, балансы, ассеты маркетплейса, RPC, адрес контракта, газ, экран подтверждения, курсы (`BNB_USD`), порядок запуска сетей.
- Новые разделы: **RPC Providers**, **USDT Contract Addresses**, **Security & Validation**, **Testing Requirements**.
- Добавлен реестр ассетов с decimals и chainId, а также тест-векторы деривации.
- Исправлены примеры кода хранения seed на iOS и Android и пример очистки буфера обмена (см. R13–R15).

---

## Core Principles

- **Multi-chain**: минимум TON (native + Jettons), Tron (TRC20 USDT), Ethereum (ERC20 USDT), BSC (BEP20 USDT).

## Mobile Apps: iOS (Crypto)

- TonSwift для TON (контракты кошелька, сообщения, Jetton transfer).
- WalletCore для Tron, Ethereum и BSC. BEP20 работает на том же EVM-стеке, что и ETH; различаются только `chainId` и RPC.

## Mobile Apps: Android (Crypto)

- Тот же WalletCore для всех EVM-цепей, включая BSC.

## Onboarding: Derivation Paths

Мультичейн-аккаунты выводятся из одного BIP39 seed:

| Сеть | Кривая | Путь | Формат адреса |
|---|---|---|---|
| TON | ed25519 (SLIP-10) | `m/44'/607'/0'` | wallet v4r2, `UQ…`/`EQ…` (**⚠️ R5**) |
| Tron | secp256k1 | `m/44'/195'/0'/0/0` | Base58Check, `T…` |
| Ethereum | secp256k1 | `m/44'/60'/0'/0/0` | `0x…`, EIP-55 |
| BSC | secp256k1 | `m/44'/60'/0'/0/0` | тот же путь, что у ETH: **один адрес работает в обеих EVM-сетях** |

Так как у ETH и BSC общий ключ, каждая EVM-транзакция подписывается строго с EIP-155 `chainId` (Ethereum `1`, BSC `56`). Подпись legacy-транзакций без chainId запрещена: такую транзакцию можно воспроизвести в другой сети.

### Тест-векторы деривации

Mnemonic `abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about`, без passphrase. iOS, Android и backend-тесты обязаны давать ровно эти значения.

| Сеть | Результат |
|---|---|
| Ethereum | `0x9858EfFD232B4033E47d90003D41EC34EcaEda94` |
| BSC | `0x9858EfFD232B4033E47d90003D41EC34EcaEda94` |
| Tron | `TUEZSdKsoDHQMeZwihtdoBiN46zxhGWYdH` |
| TON public key | `7952e94118f34607c75e23258dd9220d66ccac5a3ee074125c25068e8107bfbf` |
| TON v4r2, bounceable | `EQAzWZa6nM5mJev91wGc7VCSfBoIsYRqKJpV78N8Add9-U9d` |
| TON v4r2, non-bounceable | `UQAzWZa6nM5mJev91wGc7VCSfBoIsYRqKJpV78N8Add9-RKY` |

TON-адрес посчитан для workchain 0, `subwallet_id = 698983191`, code hash v4r2 `feb5ff6820e2ff0d9483e7e0d62c817d846789fb4ae580c878866d959dabd5c0`. Значения получены через `bip_utils` и `tonsdk` и сверены с `pytoniq-core`. ETH-вектор совпадает с общеизвестным публичным вектором для этой мнемоники.

## Wallet Home: Balances

Балансы по сетям:

- TON
- USDT (TON Jetton)
- USDT (TRC20)
- USDT (ERC20)
- USDT (BEP20)
- ETH
- BNB
- TRX

## P2P Marketplace: Assets

Фильтр ордеров по ассету: `USDT_TON`, `USDT_TRC20`, `USDT_ERC20`, `USDT_BEP20`, `TON`.

## RPC Providers

```
TON:   Toncenter API (api.toncenter.com): free tier + paid
Tron:  TronGrid (api.trongrid.io): free, API key рекомендован
ETH:   Alchemy / Infura: free tier
BSC:
  - Публичные RPC: https://bsc-dataseed.binance.org/ (free, rate limited)
  - Alchemy BSC endpoint (рекомендуется для prod)
  - QuickNode BSC
  - Для чтения баланса USDT BEP20: контракт 0x55d398326f99059fF775485246999027B3197955
```

На каждую сеть нужны минимум два провайдера с автоматическим failover. Если провайдеры расходятся в балансе или статусе транзакции, ответ не показывается как подтверждённый.

## USDT Contract Addresses

```
USDT TON (Jetton):  EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs
USDT TRC20 (Tron):  TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t
USDT ERC20 (ETH):   0xdAC17F958D2ee523a2206206994597C13D831ec7
USDT BEP20 (BSC):   0x55d398326f99059fF775485246999027B3197955   (18 decimals, не 6!)
```

Проверено: EIP-55 checksum обоих EVM-адресов, Base58Check для TRC20 (version byte `0x41`) и CRC16 TON-адреса (bounceable, mainnet, workchain 0).

**Важно про BEP20 USDT:** у него 18 decimals (как у BNB), а не 6, как у TRC20/ERC20. Код, скопированный с логики других сетей, на этом сломается. Decimals нужно явно хардкодить для каждого контракта или читать через `decimals()`.

### Реестр ассетов (единый источник для клиентов, backend и контрактов)

| Asset ID | Сеть | chainId | Контракт | Decimals |
|---|---|---|---|---|
| `TON` | TON | — | native | 9 |
| `USDT_TON` | TON | — | `EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs` | 6 |
| `TRX` | Tron | — | native | 6 |
| `USDT_TRC20` | Tron | — | `TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t` | 6 |
| `ETH` | Ethereum | 1 | native | 18 |
| `USDT_ERC20` | Ethereum | 1 | `0xdAC17F958D2ee523a2206206994597C13D831ec7` | 6 |
| `BNB` | BSC | 56 | native | 18 |
| `USDT_BEP20` | BSC | 56 | `0x55d398326f99059fF775485246999027B3197955` | 18 |

Правила работы с суммами:

- Суммы хранятся и передаются только в минимальных единицах как целые числа (`BigInt` / `BigInteger` / `Decimal`; в БД `NUMERIC(78,0)`) вместе с `asset_id`. `float`/`double` запрещены.
- Перевод «человеческих» сумм в минимальные единицы и обратно идёт только через реестр выше.
- При старте backend сверяет decimals из реестра с on-chain `decimals()` (для Jetton с метаданными). Если значения расходятся, сервис не стартует.
- Лимиты в долларах (например, $10k на сделку в escrow) задаются отдельно для каждого ассета в его единицах: `10_000 * 10^6` для USDT_TON/TRC20/ERC20 и `10_000 * 10^18` для USDT_BEP20 (**⚠️ R2**).

## Gas Reserve Logic

Минимальный остаток для оплаты газа:

- TON: 0.05 TON (**⚠️ R18**)
- Tron (для USDT TRC20): ~15 TRX или energy rental за счёт спонсора (**⚠️ R18**)
- Ethereum (для USDT ERC20): ~0.003 ETH, зависит от gas price
- BSC (для USDT BEP20): ~0.001 BNB (BSC в разы дешевле ETH)

Кнопка «Max» для native-актива вычитает резерв. Если native-баланса не хватает на газ, отправка токена блокируется до экрана подтверждения, а пользователь видит, сколько и какого токена нужно докупить.

## Transaction Confirmation Screen

ОБЯЗАТЕЛЬНО показывать:

- Адрес получателя (полностью)
- Сумму
- **Бейдж сети (TON / Tron / Ethereum / BSC): крупно, у каждой сети свой цвет.** Цвет дублируется текстом, нельзя полагаться только на цвет (дальтонизм).
- Комиссию в native-токене сети + эквивалент в USD
- Итог
- Предупреждение, если формат адреса не совпадает с выбранной сетью

**Критично:** у ERC20 и BEP20 одинаковый формат адреса (`0x…`). Пользователь легко может отправить USDT ERC20 на BEP20-адрес биржи и потерять средства. Приложение ДОЛЖНО:

1. Явно показывать выбранную сеть на каждом экране.
2. Предупреждать при отправке USDT: «Убедитесь, что получатель поддерживает USDT в сети BEP20».
3. Для адресов бирж автоматически определять сеть по whitelist (Binance deposit-адреса, Bybit и т.д.) (**⚠️ R7**).

## Backend: Rates endpoint

```
GET /rates
```

```json
{
  "TON_USD": "5.42",
  "USDT_USD": "1.00",
  "BNB_USD": "612.30",
  "ETH_USD": "3421.50",
  "TRX_USD": "0.165",
  "USD_MDL": "17.82",
  "USD_RUB": "92.40",
  "USD_UAH": "41.15"
}
```

Источники: CoinGecko API + Binance public API, кеш в Redis на 60 секунд (**⚠️ R19**).

## Deliverables: Multi-chain expansion step

5. **Multi-chain expansion.** Сети добавляются в таком порядке:
   1. USDT TRC20: крупнейший объём в регионе.
   2. USDT BEP20: второй по популярности, низкие комиссии.
   3. USDT ERC20: для совместимости с западными биржами.

---

## Security & Validation: КРИТИЧЕСКИЙ ПРИОРИТЕТ

Non-custodial не значит «безопасно по умолчанию». Атакуют не только ключи, но и UX, буфер обмена, через фишинг и MITM, а также бэкенд с данными пользователей (адреса, payment methods, суммы).

### 1. Address Validation (жёсткая проверка перед любой отправкой)

**TON-адреса:**

```swift
func validateTonAddress(_ address: String) -> Bool {
    // Два формата: EQ.../UQ... (user-friendly base64url) или raw 0:...
    guard let parsed = try? TonSwift.Address.parse(address) else { return false }
    // Checksum (CRC16) есть только у user-friendly формата, у raw "0:<hex>" его нет (см. R6)
    return true
}
```

- Адреса с флагом testnet (`kQ…`/`0Q…`, бит `0x80` в tag) в mainnet отклоняются.
- Raw-формат `0:<hex>` не содержит checksum. Если адрес вставлен в raw-формате, перед подтверждением показывается его user-friendly форма и пользователь подтверждает её отдельно.
- Native TON на незадеплоенный (uninit) кошелёк отправляется как non-bounceable (`UQ…`), иначе перевод вернётся отправителю.

**EVM-адреса (ETH / BSC):**

- 42 символа, префикс `0x`, только hex.
- EIP-55: адрес целиком в нижнем или целиком в верхнем регистре принимается без checksum. Адрес в смешанном регистре обязан пройти проверку checksum, иначе отклоняется.
- Отклонять `0x0000000000000000000000000000000000000000` и известные burn-адреса.
- Перед подтверждением выполняется `eth_getCode` в выбранной сети. Если в другой EVM-сети по этому адресу есть контракт, а в выбранной нет, показывается сильное предупреждение (например, Safe-мультисиг задеплоен только в одной сети, см. R7).

**Tron-адреса:**

- Префикс `T`, длина 34, Base58Check, version byte `0x41`.
- Проверка через `tronweb.isAddress()` (JS) или WalletCore `AnyAddress.isValid(string:coin: .tron)` (mobile). Вручную: Base58 decode + сравнение с первыми 4 байтами двойного SHA-256.

**Общие правила:**

- Проверка выполняется ДО показа экрана подтверждения, а не после.
- При вставке из буфера адрес сразу валидируется, ошибка подсвечивается красным.
- QR-скан: содержимое валидируется до заполнения полей.
- Address book (сохранённые получатели) хранит адрес вместе с меткой сети.

### 2. Network Mismatch Protection

Главная причина потерь USDT: отправка в неправильной сети.

**Правила:**

- Сеть выбирается ДО адреса, а не после.
- Смена сети очищает поле адреса.
- Для адреса `0x…` показывается предупреждение: «Это EVM-адрес. Убедитесь, что получатель принимает USDT в сети {ERC20|BEP20}. USDT, отправленный в неправильной сети, будет потерян.»
- Whitelist deposit-адресов крупных бирж с автоопределением сети: Binance, Bybit, OKX, Bitget, HTX, MEXC, Gate.io (**⚠️ R7**).
- Для сумм больше $100 обязателен чекбокс «Я подтверждаю, что сеть выбрана правильно».

### 3. Private Key / Seed Storage

**iOS** (пример исправлен, см. R14):

```swift
// 1. P-256 ключ в Secure Enclave. Приватный ключ не покидает SE,
//    для операций с ним нужна биометрия текущего набора отпечатков/лица.
guard let access = SecAccessControlCreateWithFlags(
    nil,
    kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly,
    [.privateKeyUsage, .biometryCurrentSet],
    nil
) else { throw WalletError.accessControl }

let keyAttributes: [String: Any] = [
    kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,   // SE поддерживает только P-256
    kSecAttrKeySizeInBits as String: 256,
    kSecAttrTokenID as String: kSecAttrTokenIDSecureEnclave,
    kSecPrivateKeyAttrs as String: [
        kSecAttrIsPermanent as String: true,
        kSecAttrApplicationTag as String: Data("wallet.seed.encryption".utf8),
        kSecAttrAccessControl as String: access,
    ],
]
var error: Unmanaged<CFError>?
guard let seKey = SecKeyCreateRandomKey(keyAttributes as CFDictionary, &error),
      let publicKey = SecKeyCopyPublicKey(seKey) else {
    throw error?.takeRetainedValue() ?? WalletError.keyGeneration
}

// 2. ECIES: шифрование публичным ключом проходит без биометрии,
//    расшифровка (SecKeyCreateDecryptedData с seKey) требует Face ID / Touch ID.
let algorithm: SecKeyAlgorithm = .eciesEncryptionCofactorVariableIVX963SHA256AESGCM
guard SecKeyIsAlgorithmSupported(seKey, .decrypt, algorithm),
      let encryptedSeed = SecKeyCreateEncryptedData(
          publicKey, algorithm, seedData as CFData, &error
      ) as Data? else {
    throw WalletError.encryption
}

// 3. В Keychain кладём только шифротекст. Используется ЛИБО kSecAttrAccessible,
//    ЛИБО kSecAttrAccessControl, оба сразу задавать нельзя. Биометрию уже даёт ключ SE.
let query: [String: Any] = [
    kSecClass as String: kSecClassGenericPassword,
    kSecAttrService as String: "pmrwallet.seed",
    kSecAttrAccount as String: "primary",
    kSecValueData as String: encryptedSeed,
    kSecAttrAccessible as String: kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly,
]
let status = SecItemAdd(query as CFDictionary, nil)
guard status == errSecSuccess else { throw WalletError.keychain(status) }
```

**Android** (пример дополнен fallback'ом StrongBox, см. R15):

```kotlin
// Android Keystore + BiometricPrompt для разблокировки. minSdk 30 (setUserAuthenticationParameters).
fun seedKeySpec(strongBox: Boolean) = KeyGenParameterSpec.Builder(
    "wallet_seed_key",
    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
)
    .setKeySize(256)
    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
    .setUserAuthenticationRequired(true)
    .setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG) // 0 = подтверждение на каждую операцию
    .setInvalidatedByBiometricEnrollment(true)
    .setIsStrongBoxBacked(strongBox)
    .build()

val keyGenerator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
try {
    keyGenerator.init(seedKeySpec(strongBox = true))
    keyGenerator.generateKey()
} catch (e: StrongBoxUnavailableException) {
    // StrongBox есть не на всех устройствах; без него ключ всё равно в TEE
    keyGenerator.init(seedKeySpec(strongBox = false))
    keyGenerator.generateKey()
}
// Шифрование и расшифровка идут через BiometricPrompt.authenticate(promptInfo, CryptoObject(cipher))
```

**Правила хранения:**

- Seed НИКОГДА не лежит в памяти в plaintext дольше необходимого: после использования буфер обнуляется.
- `String` для seed запрещён, только `CharArray`/`Data` с явным обнулением.
- Экран показа seed при создании защищается от снимков:
  - iOS: заблокировать скриншоты системно нельзя (**⚠️ R12**). Запись экрана детектируется через `UIScreen.main.isCaptured` с warning overlay, скриншот через `UIApplication.userDidTakeScreenshotNotification` с предупреждением, что seed скомпрометирован.
  - Android: `WindowManager.LayoutParams.FLAG_SECURE`.
- Экспорт seed каждый раз требует биометрию, даже если приложение недавно разблокировали.
- Автоблокировка: после 1 минуты простоя нужна биометрия.

### 4. Clipboard Protection

Классическая атака: malware подменяет адрес в буфере обмена на свой.

- При вставке адреса показывается превью первых и последних 6 символов и запрашивается подтверждение.
- Детекция подмены: если пользователь скопировал `EQ...abc`, а в поле попал `EQ...xyz`, показывается alert. Это работает только для копирования внутри приложения: свои адреса, address book, история (**⚠️ R16**).
- Свои адреса не остаются в буфере после копирования (пример исправлен, см. R13):

  ```swift
  import UniformTypeIdentifiers

  UIPasteboard.general.setItems(
      [[UTType.plainText.identifier: address]],
      options: [
          .localOnly: true,                                   // не уходит в Universal Clipboard
          .expirationDate: Date().addingTimeInterval(60),
      ]
  )
  ```

- Для сумм больше $500 вставка адреса отключена: только QR или ручной ввод.

### 5. Transaction Signing Flow

**Обязательные экраны перед подписью:**

1. Получатель: полный адрес, не сокращённый
2. Сумма с эквивалентом в USD
3. Сеть: крупно, цветной бейдж
4. Комиссия в native-токене + USD
5. Итог
6. Подтверждение биометрией

**Детекция подозрительных транзакций:**

- Первая отправка на этот адрес: предупреждение «Вы ещё не отправляли на этот адрес».
- Отправка больше 50% баланса требует повторного подтверждения.
- Адрес похож на известный скам (blacklist ведётся на бэкенде и обновляется через API). Сюда же относится address poisoning: адрес из истории с совпадающими первыми и последними символами, но другой серединой.
- Необычный gas price или комиссия: предупреждение.
- Успех отправки токена определяется по статусу receipt и событию `Transfer` в нужном контракте, а не по return value `transfer()` (**⚠️ R17**).

### 6. Backend Security

**Защита API:**

- Только HTTPS, HSTS preload.
- Certificate pinning в мобильных приложениях: SHA-256 пины основного и резервного сертификатов (**⚠️ R3**).
- JWT access token на 15 минут + refresh token на 30 дней с ротацией при каждом использовании (**⚠️ R23**).
- Rate limiting (Redis):
  - 100 req/min на IP для чтения
  - 20 req/min на пользователя для записи
  - 5 req/min на auth-эндпоинты
  - 3 req/hour на создание ордера с одного IP против спама (**⚠️ R11**)
- Idempotency keys на POST (защита от двойных ордеров).

**Защита данных пользователей:**

- PII в БД (payment methods, telegram username) шифруется через `pgcrypto` или app-level AES-256-GCM.
- В логах НЕТ адресов, сумм, telegram_id, IP (только хеш, **⚠️ R10**) и payment details.
- Пароли к БД, API-ключи и JWT secret хранятся только в ENV или HashiCorp Vault, никогда в коде или git.
- Для аналитики отдельная read-replica. Prod-БД доступна только с app-сервера.
- Бэкапы шифруются (age/gpg) и хранятся в отдельном регионе.
- PostgreSQL: только TLS-соединения, auth `scram-sha-256`.

**Защита от инъекций:**

- Только SQLAlchemy ORM, никакого raw SQL с конкатенацией.
- Pydantic strict mode для всех входящих данных.
- HTML-экранирование в чате сделок (защита от XSS, если бэкенд рендерит HTML).
- Валидация загружаемых файлов (receipts): проверка magic bytes, а не только MIME; re-encode через Pillow; лимит 5MB; только JPG/PNG/PDF.
- Загруженные файлы хранятся в отдельном S3/R2 bucket с pre-signed URLs, НЕ на app-сервере.

**Защита от сетевых атак:**

- Cloudflare перед API: DDoS protection, WAF, Bot Fight Mode.
- fail2ban на SSH + правила fail2ban на подозрительные паттерны API.
- SSH: только ключи, порт не 22, root login отключён.
- Файрвол: открыт только 443 (API) и SSH на нестандартном порту с IP whitelist (**⚠️ R4**).
- Автоматические обновления безопасности (`unattended-upgrades`).
- Регулярный pentest / bug bounty (HackerOne, Immunefi).

### 7. P2P Trade Security

**Защита от распространённых скамов:**

- **Fake payment confirmation**: продавец сам вводит сумму полученного фиата, система сверяет её с ожидаемой. При расхождении автоматически открывается dispute.
- **Chargeback risk (банковские карты)**: для карточных платежей time-lock 30 минут на release после подтверждения оплаты (**⚠️ R8**).
- **Social engineering в чате**:
  - Фильтр внешних ссылок в сообщениях (разрешён whitelist).
  - Детекция попыток увести общение в Telegram/WhatsApp, пользователь получает предупреждение.
  - Запрет на отправку изображений с текстом (OCR ищет реквизиты вне системы) (**⚠️ R9**).
- **Fake receipt images**: проверка EXIF, поиск по perceptual hash в базе ранее загруженных receipts.
- **Account takeover**: 2FA обязательна для сделок больше $500 (Telegram login code + биометрия приложения) (**⚠️ R22**).
- **Sybil attack на репутацию**: verified badge минимум после 10 сделок, детекция подозрительных паттернов (одно устройство и много аккаунтов, по device fingerprint).

**Защита escrow:**

- Если в течение 24 часов нет действий, автоматически выполняется refund (**⚠️ R1**).
- Арбитр не может единолично сделать release: нужен мультисиг 2 из 3 (buyer ИЛИ seller + arbiter).
- Арбитр не может переводить средства на свой адрес (ограничение в контракте).
- Все действия арбитра логируются on-chain.

### 8. Supply Chain Security

- Сканирование зависимостей: `npm audit`, `pip-audit`, Dependabot, Snyk.
- Lock-файлы в репозитории, воспроизводимые сборки.
- iOS: Swift Package Manager с закреплёнными версиями, никакого live-at-head.
- Android: Gradle version catalog, включён dependency verification.
- Backend: `pyproject.toml` с точными версиями, lock через `pip-compile`.
- Docker images: только официальные базовые, закреплённые по digest (не по tag).
- Секреты CI/CD хранятся в GitHub Actions secrets / Vault, не в коде.
- Подпись релизов (iOS автоматически, Android APK signing v2+).

### 9. Smart Contract Security

- Внешний аудит до mainnet (CertiK, Hacken, TonTech): $15–50k. Аудит нужен для каждого контракта отдельно: TON (FunC/Tact), Tron (Solidity/TVM), EVM (Solidity). EVM-контракт один на ETH и BSC, но конфигурация деплоя (адрес токена, decimals, лимиты) проверяется для каждой сети.
- Formal verification критичных функций (release, refund, resolve_dispute).
- Bug bounty после запуска (Immunefi): минимум $50k за critical.
- Pausable contract с мультисигом 3 из 5 на случай эксплойта (**⚠️ R21**).
- Rate limits в контракте: в v1 максимум $10k на сделку, лимит повышается по мере тестирования (**⚠️ R2**).
- Работа с USDT через SafeERC20-обёртку (**⚠️ R17**).
- Testnet-период минимум 2 месяца с реальными тестовыми сделками до mainnet.

### 10. Incident Response

- Статус-страница для даунтаймов (status.pmrwallet.com).
- Аварийная кнопка в приложении «pause all my orders»: не требует бэкенда, подписывается локально (**⚠️ R20**).
- Процедура disclosure: `security@pmrwallet.com` с PGP-ключом в `/.well-known/security.txt`.
- Попытки взлома логируются в SIEM (минимум Elasticsearch + Kibana).
- Регулярные бэкапы с ежемесячной проверкой восстановления.

### 11. Compliance Minimums

Даже без лицензии (non-custodial):

- Privacy Policy с явным описанием, что хранится и что не хранится.
- Terms of Service с disclaimers о рисках криптовалют.
- Data Safety declaration для Google Play (совместимая с GDPR).
- Точный App Store Privacy Nutrition Label.
- Удаление аккаунта кнопкой в приложении (GDPR, right to erasure).
- Экспорт своих данных по запросу (GDPR, right to data portability).
- Данные не хранятся дольше необходимого: чаты сделок удаляются через 90 дней после завершения.

---

## Testing Requirements

Обязательные тесты для каждого критичного компонента.

**Validation tests:**

- Все известные форматы валидных адресов каждой сети → PASS.
- Невалидные адреса (длина, checksum, другая сеть) → REJECT.
- TON: testnet-адрес в mainnet → REJECT; raw `0:<hex>` → требует отдельного подтверждения.
- EVM: адрес в смешанном регистре с неверным EIP-55 → REJECT; адрес целиком в нижнем регистре → PASS.
- Fuzzing адресов (случайные байты) → никогда не падает.

**Amount / decimals tests:**

- `"1.5"` USDT_BEP20 → `1500000000000000000`; `"1.5"` USDT_TRC20/ERC20/TON → `1500000`.
- Round-trip форматирования для каждого ассета из реестра без потери точности.
- Расхождение decimals между реестром и on-chain → сервис не стартует.

**Crypto tests:**

- Генерация → экспорт → импорт seed → адреса совпадают.
- Тест-векторы деривации из раздела [Onboarding](#тест-векторы-деривации) совпадают на iOS, Android и backend.
- Подпись → верификация подписи.
- EVM-транзакция, подписанная для chainId 1, отклоняется узлом BSC (chainId 56), и наоборот.
- Шифрование → расшифровка seed с правильной и неправильной биометрией.

**Backend tests:**

- Все эндпоинты с невалидными токенами → 401.
- Все эндпоинты с правами другого пользователя → 403.
- Попытки SQL injection в каждом параметре → безопасно.
- Rate limiting срабатывает после N запросов.
- WebSocket auth работает, невалидный токен → disconnect.

**E2E trade tests (на testnet):**

- Happy path: order → accept → payment → release → review.
- Dispute path: order → accept → payment → dispute → решение арбитра.
- Timeout path: order → accept → 24 часа без действий → auto-refund.
- Timeout после оплаты: order → accept → buyer отмечает «оплачено» → seller 24 часа бездействует → auto-dispute, НЕ refund (см. R1).
- Chargeback path: release → попытка dispute после time-lock.
- Каждый E2E-сценарий прогоняется для всех ассетов маркетплейса, включая USDT_BEP20 (18 decimals).

---

## Замечания ревью

Найдены при сведении ревизии. Требования выше не изменены, решение по каждому пункту за владельцем спецификации. Исключение — R13–R15: там примеры кода были нерабочими и исправлены прямо в тексте.

### Критичные (потеря средств или обход защиты)

**R1. Auto-refund через 24 часа позволяет продавцу украсть фиат.** Продавец получает фиат, молчит 24 часа, и escrow возвращает ему крипту. Timeout должен зависеть от состояния сделки: если покупатель НЕ отметил оплату, выполняется refund продавцу; если отметил, открывается auto-dispute, а не refund. Это нужно закрепить и в контракте, и в E2E-тестах (сценарий добавлен в Testing Requirements).

**R2. Decimals в лимитах контракта.** Лимит «$10k на сделку» и любые суммы в контракте задаются в единицах конкретного токена. На BSC это `10_000 * 10^18`. Если перенести константу `10_000 * 10^6` с других сетей, лимит на BSC станет $0.01, и все сделки будут отклоняться. Обратная ошибка в форматировании на клиенте завысит суммы в 10^12 раз.

**R3. Certificate pinning конфликтует с Cloudflare.** Cloudflare сам выпускает и ротирует edge-сертификаты (в том числе у разных CA). Пины на leaf-сертификат сломают приложение при очередной ротации. Варианты: загрузить свой сертификат в Cloudflare (Custom Certificates, доступно не на всех планах) и пинить SPKI своих ключей (основной + резервный, резервный хранится офлайн) либо пинить набор CA. Это решение нужно принять до первого релиза: пины меняются только обновлением приложения.

**R4. Обход Cloudflare напрямую на origin.** Если 443 открыт для всех, WAF и DDoS-защиту можно обойти, обратившись по IP сервера. Нужно разрешить 443 только с IP-диапазонов Cloudflare (или использовать Cloudflare Tunnel без открытых входящих портов) и включить Authenticated Origin Pulls.

**R5. TON-адрес из BIP39 не совпадёт с Tonkeeper.** Нативные TON-кошельки (Tonkeeper, MyTonWallet) используют собственную схему мнемоники TON, а не BIP39 + `m/44'/607'/0'`. Схема из спецификации совпадает с Trust Wallet и Ledger. Если пользователь импортирует seed в Tonkeeper, он увидит другой адрес или ошибку импорта. Что нужно решить:
- в UX явно указать, с какими кошельками совместим seed;
- деривацию TON на iOS делать через WalletCore (тот же код, что на Android), а TonSwift использовать только для контрактов и сообщений;
- зафиксировать версию кошелька (v4r2 или W5, который сейчас по умолчанию в Tonkeeper). При импорте проверять балансы на обеих версиях.

**R6. У raw TON-адресов нет checksum.** Комментарий «Проверка checksum встроена в `Address.parse`» верен только для user-friendly формата (`EQ…`/`UQ…`, CRC16). Адрес `0:<hex>` с опечаткой пройдёт парсинг. Правило отдельного подтверждения добавлено в раздел Address Validation.

**R7. Автоопределение сети по whitelist адресов бирж нереализуемо.** Биржи выдают каждому пользователю свой deposit-адрес, публичного списка таких адресов нет. По самому `0x`-адресу нельзя понять, ERC20 это или BEP20: Binance, например, принимает обе сети на один адрес. Реализуемые замены:
- запрашивать в обеих EVM-сетях `eth_getCode`, nonce и историю USDT по адресу и предупреждать, если в выбранной сети активности нет, а в другой есть;
- самое опасное — контрактные кошельки (Safe и т.п.): они существуют только в той сети, где задеплоены, и средства, отправленные на тот же адрес в другой сети, могут быть невозвратны.

**R8. Time-lock 30 минут не защищает от chargeback.** Окно chargeback по картам — недели и месяцы, а не минуты. Реальные меры: ограничить карточные методы для новых аккаунтов, ввести лимиты сумм по репутации и предпочитать необратимые методы оплаты. 30-минутный lock защищает только от мгновенной отмены перевода.

### Важные

**R9. Запрет изображений с текстом противоречит загрузке receipts.** Чек оплаты — это изображение с текстом и реквизитами. Нужно уточнить: OCR-фильтр применяется только к изображениям в чате, а receipts идут через отдельный flow с проверками из раздела 6 и 7. OCR ищет телефоны и номера карт, которые не совпадают с payment method ордера.

**R10. Хеш IP обратим.** Простой SHA-256 от IPv4 восстанавливается перебором всех 2^32 значений за минуты. Нужен keyed hash (HMAC с секретом из Vault) с периодической ротацией ключа.

**R11. Лимит ордеров по IP бьёт по мобильным пользователям.** У мобильных операторов CGNAT: тысячи абонентов выходят через несколько IP, и лимит 3 ордера в час на IP заблокирует целого оператора. Основной лимит должен считаться по пользователю и устройству, а IP использовать как дополнительный сигнал.

**R12. На iOS нельзя запретить скриншоты.** «Отключить screenshot» на iOS невозможно, можно только детектировать запись (`isCaptured`) и сам факт скриншота постфактум. Формулировка в разделе 3 уточнена.

**R13. Пример очистки буфера был нерабочим.** `setItems([], options: [.expirationDate: …])` записывает пустой буфер со сроком жизни, а сам адрес остаётся без срока. Исправлено: адрес записывается вместе с `.expirationDate` и `.localOnly`.

**R14. Пример хранения seed на iOS был нерабочим.**
- `kSecAttrAccessible` и `kSecAttrAccessControl` взаимоисключающие, вместе `SecItemAdd` вернёт ошибку.
- `.privateKeyUsage` относится к ключам Secure Enclave, а не к `kSecClassGenericPassword`.
- Secure Enclave не выполняет симметричное шифрование и хранит только P-256 ключи; данные шифруются через ECIES.
- `SecureEnclaveKey.generate` не существует в iOS SDK.

Пример переписан на реальное API.

**R15. StrongBox не откатывается на TEE автоматически.** Комментарий «hardware-backed если доступно» неверен: на устройствах без StrongBox `generateKey()` бросает `StrongBoxUnavailableException`. Добавлен явный fallback.

**R16. Подмену в буфере можно заметить только для своих данных.** Приложение не знает, что пользователь скопировал в другом приложении. Сравнение «скопировал X, вставилось Y» возможно только для копирования внутри приложения. Для внешних адресов остаются превью, подтверждение и правило про $500.

**R17. USDT ERC20 не соответствует стандарту ERC20.** `transfer`/`approve` не возвращают `bool`, а `approve` с ненулевого allowance на ненулевой ревертится (сначала нужно выставить 0). В контракте escrow нужна SafeERC20-обёртка. На клиенте успех определяется по статусу receipt и событию `Transfer`.

**R18. Резервы газа нужно считать динамически.**
- Tron: стоимость USDT-перевода зависит от того, есть ли у получателя USDT (примерно 65k energy против примерно 130k energy для адреса с нулевым балансом USDT), и от текущей цены energy, которую меняет governance. 15 TRX может не хватить. Нужно делать estimate перед отправкой и добавлять запас.
- TON: Jetton transfer прикладывает около 0.05 TON (излишек возвращается), а комиссия самого кошелька списывается сверху. Резерв ровно 0.05 TON на грани: лучше 0.1 TON или расчёт через эмуляцию.
- BSC и ETH: указанных значений достаточно, но лучше тоже считать через `eth_estimateGas` × текущий gas price с запасом.

**R19. Источники и формат курсов.**
- Фиатные пары (`USD_MDL`, `USD_RUB`, `USD_UAH`) лучше брать у центробанков (BNM, ЦБ РФ, НБУ) или FX-агрегатора, а не у криптоисточников.
- Если целевой регион — ПМР, в ответе нет приднестровского рубля (`USD_PRB`, источник: Приднестровский республиканский банк).
- Binance API отдаёт HTTP 451 на запросы с IP в части юрисдикций (например, США). Это нужно учесть при выборе хостинга.
- В ответ стоит добавить `updated_at`. Если курс старше заданного порога, экран подтверждения помечает USD-эквивалент как устаревший.

**R20. «Pause all my orders» без бэкенда.** Открытые ордера лежат в orderbook на бэкенде, поэтому локально подписанное сообщение всё равно нужно куда-то доставить: через backend или любой ретранслятор, который проверяет подпись. Активные сделки в escrow односторонне поставить на паузу нельзя. Нужно уточнить, что кнопка снимает только открытые ордера.

**R21. Pause в контракте не должен замораживать средства пользователей.** Если пауза блокирует refund и timeout, мультисиг 3 из 5 получает контроль над чужими средствами, а это противоречит non-custodial модели. Пауза должна блокировать только создание новых сделок, а refund и timeout должны работать всегда.

### Мелкие

**R22. Telegram login code недоступен сторонним приложениям.** Код входа Telegram может отправлять только сам Telegram. Для 2FA нужен OTP через бота проекта (или официальный Telegram Gateway API) плюс биометрия.

**R23. Ротация refresh token без детекции повторного использования неполная.** При повторном использовании уже ротированного refresh token нужно отзывать всё семейство токенов этой сессии: это признак кражи токена.
