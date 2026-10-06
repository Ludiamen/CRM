# Образцы для тестов вложений сервис-деска

Задача T-3002 среза 003 (PLAN-003, «Вложения»; TASKS-003, решение Opus 6). Образцы нужны тестам приёма вложений:
проверке «исполняемый файл» и «архив с паролем» своей проверкой заголовков и второму рубежу — clamd с
`AlertEncryptedArchive yes` (T-3003). Тесты и контракт CONTRACT-003.md (T-3100) называют образцы по именам из таблиц
ниже. Письма в репозитории не лежат: тесты собирают их сами (`build_mail`).

Собрал Opus 2026-10-06 на машине разработки. Сборочный скрипт и проверка лежат вне репозитория:
`crm-work/slice003/stage1/t3002/make_fixtures.py` и `verify.py`, протокол проверки — `verify.txt` там же (131
проверка, ошибок нет). Образцы `enc_zip_second_entry.zip` и `not_exe_dos_mz.bin` добавлены по проверке R-stage1a
(ключ `--r-stage1a` сборочного скрипта собирает только их, прежние файлы не пересобираются). Средства: Info-ZIP `zip` 3.0, 7-Zip 23.01, RAR 7.00 и UNRAR 7.00, Pillow 11.3.0, `file`
(libmagic), olefile 0.47 (только для проверки, в зависимости проекта не входит).

Пароль архивов случайный (`secrets.token_urlsafe(9)` на каждую сборку) и нигде не сохранён. Тестам он не нужен:
они проверяют только, что архив с паролем. Целостность каждого архива со своим паролем проверена при сборке
(`7z t`, `unrar t`). Строки EICAR в образцах нет (проверено поиском по всем файлам). Исполняемые образцы — не
программы, а только заголовки форматов: запускать там нечего.

## Архивы

Внутри собранных архивов — `sample.txt` (строка «Образец T-3002 для проверки архивов (срез 003).»). Архивы «со
сжатым заголовком» содержат 30 таких файлов `f01.txt`…`f30.txt`: только тогда 7-Zip сжимает заголовок так, что
кодек AES в нём простым поиском не виден.

| Файл | Что это | Чем собран | Что проверено (по байтам и сторонним средством) |
|---|---|---|---|
| enc_zip_zipcrypto.zip | ZIP, пароль ZipCrypto | `zip -X -P <пароль>` | `flag_bits & 1` у элемента; метода 99 нет; `7z l -slt` — `Encrypted = +` |
| enc_zip_aes.zip | ZIP, пароль WinZip AES-256 | `7z a -tzip -mem=AES256 -p<пароль>` | `flag_bits & 1` и метод 99 (AES); `7z l -slt` — `Encrypted = +` |
| enc_zip_second_entry.zip | ZIP, первый элемент `readme.txt` без пароля, второй `sample.txt` — ZipCrypto | `zip -X`, затем `zip -X -P <пароль>` в тот же архив | у первого элемента `flag_bits & 1` нет, у второго есть; `7z l -slt` — один `Encrypted = +` и один `Encrypted = -`. План: «бит шифрования … у любого элемента» |
| plain.zip | ZIP без пароля | `zip -X` | `flag_bits & 1` нет; метода 99 нет; `Encrypted = +` нет |
| nested_enc_zip.zip | обычный ZIP, внутри `inner.zip` — копия enc_zip_zipcrypto.zip | `zip -X` | у внешнего элемента шифрования нет; у элемента внутри `inner.zip` — `flag_bits & 1`. Своя проверка заголовков видит только верхний уровень, вложенный ловит clamd |
| enc_rar5_data.rar | RAR5, зашифрованы данные файла | `rar a -ma5 -p<пароль>` | CRC32 заголовков; у заголовка файла (тип 2) в области extra запись 0x01 «шифрование файла»; первого блока типа 4 нет; `unrar l` помечает файл `*`; `file` — `RAR archive data, v5` |
| enc_rar5_headers.rar | RAR5, зашифрованы заголовки | `rar a -ma5 -hp<пароль>` | первый блок после сигнатуры — тип 4 «шифрование архива»; `unrar l` без пароля файлов не показывает |
| plain_rar5.rar | RAR5 без пароля | `rar a -ma5` | ни блока типа 4, ни записи extra 0x01; `unrar l` — файл без `*` |
| enc_rar4_data.rar | RAR 4 (формат RAR 2.9–4.x), зашифрованы данные файлов | настоящий файл `rar3-comment-psw.rar` (см. «RAR4») | сигнатура `Rar!\x1a\x07\x00`; главный заголовок 0x73 без флага 0x0080; у двух заголовков файлов 0x74 флаг 0x0004; CRC заголовков совпали; `unrar l` — оба файла с `*`, «Details: RAR 4»; `file` — `RAR archive data, v4` |
| enc_rar4_headers.rar | RAR 4, зашифрованы заголовки | настоящий файл `rar3-comment-hpsw.rar` | у главного заголовка 0x73 флаг 0x0080; `unrar l` без пароля файлов не показывает; `file` — `flags: EncryptedBlockHeader` |
| plain_rar4.rar | RAR 4 без пароля | настоящий файл `rar3-comment-plain.rar` | флагов 0x0080 и 0x0004 нет; `unrar l` — файлы без `*` |
| enc_7z_plain_header.7z | 7z, пароль, простой заголовок | `7z a -t7z -p<пароль> -mhe=off -mhc=off` | следующий заголовок начинается с 0x01 (kHeader); кодек AES `06 F1 07 01` в нём находится простым поиском; `Encrypted = +` |
| enc_7z_encrypted_header.7z | 7z, пароль, зашифрованный заголовок | `7z a -t7z -p<пароль> -mhe=on` | заголовок начинается с 0x17 (kEncodedHeader); кодек AES в нём находится простым поиском; `7z l` с неверным паролем архив не открывает |
| enc_7z_compressed_header.7z | 7z, пароль на данных, заголовок сжат и не зашифрован | `7z a -t7z -p<пароль> -mhe=off -mhc=on`, 30 файлов | заголовок начинается с 0x17; кодек AES простым поиском **не** находится (он внутри сжатого LZMA заголовка); `Encrypted = +` |
| plain_7z_plain_header.7z | 7z без пароля, простой заголовок | `7z a -t7z -mhc=off` | 0x01; AES нет; `Encrypted = +` нет |
| plain_7z_compressed_header.7z | 7z без пароля, сжатый заголовок | `7z a -t7z -mhc=on`, 30 файлов | 0x17; AES нет; `Encrypted = +` нет |

### RAR4

RAR 7.00 архивы RAR4 больше не создаёт (ключ `-ma4` — «Unknown option», файл фактов `F5-files.md`). Поэтому три
образца RAR4 — настоящие архивы из тестов библиотеки rarfile:
`https://github.com/markokr/rarfile`, каталог `test/files/`, коммит `d2f7df6fc843dae356fd6b0a85971dc36fd6e757`
(2026-08-23), файлы скачаны 2026-10-06 и положены без изменений (sha256 — в таблице ниже). Лицензия репозитория —
ISC, её текст с уведомлением об авторском праве лежит рядом: `LICENSE-rarfile.txt`, как требует сама лицензия. Внутри
архивов — пустые `file1.txt` и `file2.txt` (2010-11-02) и комментарий архива «RARcomment». Пароль этих архивов тестам
тоже не нужен.

На этих настоящих файлах подтверждены флаги RAR4, которые в плане взяты из исходника rarfile и на настоящем RAR4
до сих пор не проверялись (PLAN-003, «Вложения», п. 3; F5): 0x0080 главного заголовка — «заголовки зашифрованы»,
0x0004 заголовка файла — «файл с паролем».

## Исполняемые файлы и похожие на них

Все собраны байтами по описанию форматов (`make_fixtures.py`). Расширение у них нейтральное (`.bin`, `.zip`,
`.txt`), чтобы тест проверял именно содержимое; имя файла при загрузке тест задаёт сам.

| Файл | Что это | Как собран | Что проверено |
|---|---|---|---|
| exe_pe.bin | Windows PE | DOS-заголовок `MZ`, `e_lfanew` (смещение 0x3C) = 0x40, по нему `PE\0\0`, заголовок COFF (i386, исполняемый образ) и опциональный заголовок PE32 | `MZ` и `PE\0\0` по `e_lfanew`; `file` — `PE32 executable (console) Intel 80386, for MS Windows` |
| exe_elf.bin | ELF | заголовок ELF64 (`\x7fELF`, LSB, `ET_EXEC`, x86-64) | `file` — `ELF 64-bit LSB executable, x86-64` |
| exe_macho64_le.bin | Mach-O 64, обратный порядок байт | `CF FA ED FE`, x86_64, `MH_EXECUTE` | `file` — `Mach-O 64-bit x86_64 executable` |
| exe_macho32_be.bin | Mach-O 32, прямой порядок байт | `FE ED FA CE`, PowerPC, `MH_EXECUTE` | `file` — `Mach-O ppc executable` |
| exe_macho_fat.bin | универсальный Mach-O | `CA FE BA BE`, число архитектур 2 и две записи `fat_arch` | число архитектур 2 (меньше 45); `file` — `Mach-O universal binary with 2 architectures` |
| exe_script.bin | скрипт | текст, начинается с `#!/bin/sh` | `#!` в начале; `file` — `POSIX shell script` |
| exe_msi.bin | установщик MSI | составной файл OLE (CFB версии 3, сектор 512 байт) без потоков, корень с CLSID установщика `000C1084-0000-0000-C000-000000000046` | сигнатура `D0 CF 11 E0 A1 B1 1A E1`; olefile читает корень, CLSID тот же; `file` — `Composite Document File V2 Document` |
| exe_jar.zip | JAR | ZIP с `META-INF/MANIFEST.MF` и `sample.txt` (без классов) | `META-INF/MANIFEST.MF` в списке элементов |
| not_exe_java_class.bin | класс Java — **не** Mach-O | `CA FE BA BE`, версия формата 52 (Java 8) | версия 52 (не меньше 45); `file` — `compiled Java class data, version 52.0` |
| not_exe_ole_doc.bin | старый документ Word — **не** MSI | тот же CFB, корень с CLSID Word `00020906-0000-0000-C000-000000000046` | olefile — CLSID Word; `file` — `Composite Document File V2 Document` |
| not_exe_dos_mz.bin | файл DOS с `MZ` — **не** PE | заголовок DOS 64 байта, `e_lfanew` = 0x40 указывает внутрь файла, там текст, а не `PE\0\0` | `MZ`; по `e_lfanew` внутри файла не `PE\0\0`; `file` — `MS-DOS executable, MZ for MS-DOS` |
| not_exe_mz_text.txt | текст, который начинается с букв `MZ`, — **не** PE | текст UTF-8 | по `e_lfanew` из байтов текста `PE\0\0` нет (смещение за концом файла); `file` — текст |
| not_exe_odf_manifest.zip | ZIP как документ ODF — **не** JAR | `mimetype`, `META-INF/manifest.xml`, `content.xml` | `META-INF/manifest.xml` есть, `META-INF/MANIFEST.MF` нет |

**MSI.** Настоящий MSI в репозиторий не кладётся: под рукой только распространяемые пакеты среды выполнения
Microsoft, их лицензия не наша. CLSID установщика сверен на двух настоящих MSI на машине разработки
(`vc_runtimeMinimum_x86.msi` из пакета Visual C++ 14.0.24215 и ещё один из каталога Installer в Wine): olefile
0.47 у обоих даёт корень `000C1084-0000-0000-C000-000000000046`. Так подтверждён CLSID, который в F5 был взят из
документации Windows Installer и на настоящем MSI не проверялся. Образец `exe_msi.bin` собран байтами с этим CLSID.
CLSID Word для `not_exe_ole_doc.bin` взят из F5: там он сверен на настоящих файлах `.doc`.

## Картинки

| Файл | Что это | Как собран | Что проверено |
|---|---|---|---|
| image.png | PNG 32×24, градиент | Pillow 11.3.0 | Pillow открывает и проверяет (`verify`), формат PNG; `file` — PNG |
| image.jpg | JPEG 32×24, тот же градиент, качество 85 | Pillow 11.3.0 | то же, JPEG |

## Контрольные суммы (sha256)

| Файл | Байт | sha256 |
|---|---|---|
| enc_7z_compressed_header.7z | 560 | ca08265e052b45f0886cebbc7ec4f5de12dc174b5e7365ee4ea0994cf07d4292 |
| enc_7z_encrypted_header.7z | 287 | f3d27e48732d54c88e9ebbffa4dd92807efb50bc42e8463da3b40d5a0f6adbd7 |
| enc_7z_plain_header.7z | 226 | 17f15b01392bd6d3ccfbd46b56652fefdec200721500362b003407b9a2dd0368 |
| enc_rar4_data.rar | 332 | ffb9b41571ac4d56ebf9a5ce5323740ea6150d66823b66abf7566f8dd2639803 |
| enc_rar4_headers.rar | 484 | 29c61403d1e7cec0b15eb7e33cfa217cebd56bf1a4a78a2642715eca474350b2 |
| enc_rar5_data.rar | 221 | 347ea04f99bc6e2064a881e66d7207d1badb977836ca8f6ddc0060595a9b0464 |
| enc_rar5_headers.rar | 318 | 8699096136c0262d63ea089a6bad051f931852f6068088814758ce30825a91d1 |
| enc_zip_aes.zip | 280 | 0a59a1f08d0f1d498eca9a83b3f17488d4238c1c1931625c134169c903817038 |
| enc_zip_second_entry.zip | 375 | a61ba1e884b0c738afd4c4c739de9f3b1d92e13e6ca839a7c3b8889be1423845 |
| enc_zip_zipcrypto.zip | 221 | 72bb666439822946515de7d6274e5e05be9d00b69ce053c64bc3ab8446108cbb |
| exe_elf.bin | 64 | 51224867e5fb13d0c6052397c9f4959c7c87bb8bc7d750c91429728a18b507d9 |
| exe_jar.zip | 356 | cb65281ad1b333ac1c235a03e0b63e6a69e62fe77e1bd11514a4096053ae9e1b |
| exe_macho32_be.bin | 28 | 97c8845843b97ff8be7376af554d383ff5dc94e6345206f7138be81f0a1d0341 |
| exe_macho64_le.bin | 32 | bc3453b219cc2be24610500cecccb0138e803dd7524dbafcbddd4c89ebf53efc |
| exe_macho_fat.bin | 48 | 76635b21821bf5ac3338ae07e1333ffa9064b3eccd7a8a1ea3a3b300f3e66368 |
| exe_msi.bin | 1536 | 39809e04e842c493a0cd8a5686ca5df098edda74253f7d027a80f79c2cbcb17f |
| exe_pe.bin | 312 | 85687a706660e8041a0bf53ad333771d99e281003dc53977d4bb19a154872c55 |
| exe_script.bin | 123 | 765705645e266c07164984ccbe720858da049358916c065e9eec236e81b950ad |
| image.jpg | 751 | b7e187f1ad9e88a6fb29d0b435f5f8fb097c4339dcf57b884861cb7f5a3661be |
| image.png | 99 | c73989382f4b9bd97386a4729ea7c50937ef5ccb4b2312773eb2d5eeaf14d180 |
| LICENSE-rarfile.txt | 756 | 44defaa4d449e7837e6c2bc692751c5dfd438baa3677b9e25a9a41092d2aa9a8 |
| nested_enc_zip.zip | 337 | 742ff1bc1ad35b1bf595ee6382bd9b891b33ca8ffc372555d58fb4c6edc97bac |
| not_exe_dos_mz.bin | 121 | a7fa84d0d69ddb94cd6ad722f735c93c2900921a8b59211fc248ae0e47b579ed |
| not_exe_java_class.bin | 24 | f13ceba1d4b6c8861febdb2193a30cf42764388b22fd304bfa9bf8dd7368dde8 |
| not_exe_mz_text.txt | 254 | bbfdacef3ad293599370f4562212541cf90b848c8e1dd685fedc802d77499a9d |
| not_exe_odf_manifest.zip | 543 | 233d2cff2f1df1333e35ad570cf3786868a8847e046a43380a21a1d4fee73c97 |
| not_exe_ole_doc.bin | 1536 | 49909c2a7fd23dd1939883529bf194618229952ba904bf8a7921d7454ce03a2e |
| plain.zip | 193 | e5abac2ffdb2e94e832a559f78e893992ef8ece089df25fbbd1f47916b412582 |
| plain_7z_compressed_header.7z | 527 | 92dbb1da45209eab413b6f53b19d3584aaadb109aa373d20ca89614570650d93 |
| plain_7z_plain_header.7z | 209 | fe194dc04c68c1435615812a0ee641dd9149864d65b50be8cab6d54e981595ab |
| plain_rar4.rar | 300 | 224a3f0aacab5cbb140b72dde616280a871589f251b9147bdb55b49651661813 |
| plain_rar5.rar | 153 | dc82f32c8adf470903ac3fedd4209d083bdae8744c210a3e2fab05f5b57a4b0e |

## Чего здесь нет

- Файлов больше 20 МБ и писем больше 50 МБ: тесты собирают их на лету, а время проверки 20 МБ в clamd меряет T-3003
  на несжимаемом ZIP, который в репозиторий не кладётся.
- Ответов clamd на эти образцы: они записаны в разделе «Подготовка: clamd» отчёта TASKS-003 (T-3003), в
  репозиторий не кладутся.
- Остальных магических чисел Mach-O (`FE ED FA CF`, `CE FA ED FE`, `BE BA FE CA`, `CA FE BA BF`): это четыре байта в
  начале файла, тест может собрать их сам по таблице плана.
- `CA FE BA BE` с числом 45 и больше в байтах 4–7 (по плану это класс Java, а не универсальный Mach-O) и JAR, у
  которого `META-INF/MANIFEST.MF` не первый элемент: тест собирает их сам (`struct.pack`, `zipfile`).
