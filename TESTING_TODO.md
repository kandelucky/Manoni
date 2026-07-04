# Manoni — ტესტირების თოდო

## სტატუსი (ავტომატური ნაწილი — მზადაა)

`(მე)` პუნქტების ავტომატური ტესტები დაწერილია და **ყველა გადის**:

- `tests/test_behavior.py` — 39/39: ყველა imaging ეფექტი (მიმართულება, no-op,
  hue/sat gating, pipeline: cache==flat / fast / neutral).
- `tests/test_logic.py` — 19/19: filters/actions JSON safety, unique naming,
  group bookkeeping, resolution-independent action replay, resize maths,
  save-metadata (orientation→1, ICC).
- `tests/test_storage.py` — 4/4: atomic `save_json`, `unique_path` no-clobber.
- `tests/test_imaging_golden.py` — 50/50 (არსებული, უცვლელი).

გაშვება: `python tests/test_behavior.py` (იგივე logic/storage). ქვემოთ დარჩენილი
`(შენ)` პუნქტები ხელით შესამოწმებელია.

---

აღნიშვნები:

- **(მე)** — ავტომატური ტესტი: კოდით ვამოწმებ. გამოთვლა/ლოგიკა/პიქსელები/ფაილები
  სწორია, ნეიტრალი = უცვლელი, კრახი არ ხდება, preview == save. ესთეტიკას ვერ ვამბობ.
- **(შენ)** — თვალით/ხელით: სურათი „კარგად“ გამოიყურება, დრეგი/კურსორი/overlay ზუსტია,
  ნატიური დიალოგები, კლავიშები, DPI, ლაგი.
- **(ორივე)** — მე ვამოწმებ მიმართულებას+კრახს, შენ ადასტურებ რომ თვალით სწორია.

---

## 0. ბირთვი: pipeline + Edits

- [ ] **(მე)** `Edits()` default — ყველა ველი ნეიტრალურია (1.0, ეფექტები 0.0).
- [ ] **(მე)** `apply_edits` ნეიტრალურ `Edits`-ზე — გამოსახულება არ იცვლება.
- [ ] **(მე)** `apply_edits_cached` == `apply_edits` (ქეშირებული == ბრტყელი, byte-identical).
- [ ] **(მე)** `fast=True` ტოვებს მძიმე passes-ს (denoise/dehaze/clarity/texture/sharpen/focus/grain).
- [ ] **(მე)** stages-ის რიგი — ეფექტების კომპოზიცია იმ თანმიმდევრობით რაც `edit_stages`-შია.
- [ ] **(შენ)** preview პატარაზე ≈ full-res save (scale-invariance) — თვალით.

## 1. Basic — White balance

- [ ] **(მე)** Temperature — >1 წითელს ამატებს/ლურჯს აკლებს, <1 პირიქით; 1.0 = no-op.
- [ ] **(მე)** Tint — >1 მწვანეს აკლებს (magenta), <1 მწვანეს ამატებს; 1.0 = no-op.
- [ ] **(შენ)** ორივე — თბილი/ცივი ბალანსი ცოცხალ ფოტოზე ბუნებრივია.

## 2. Basic — Tone

- [ ] **(მე)** Exposure (brightness) — სიკაშკაშე იზრდება/მცირდება; 1.0 = no-op.
- [ ] **(მე)** Contrast — 1.0 = no-op, მიმართულება სწორია.
- [ ] **(მე)** Highlights — მხოლოდ ნათელ დიაპაზონს ცვლის (tone_lut hump ~0.62).
- [ ] **(მე)** Shadows — მხოლოდ მუქ დიაპაზონს (hump ~0.38).
- [ ] **(მე)** Whites — მხოლოდ ზედა ~28% (clip point).
- [ ] **(მე)** Blacks — მხოლოდ ქვედა ~28% (clip point).
- [ ] **(მე)** ოთხივე ნეიტრალურ მდგომარეობაში `tone_lut` = None (passa გამოტოვებულია).
- [ ] **(შენ)** ოთხივე ერთმანეთისგან ვიზუალურად განსხვავებულია (highlights ≠ whites და ა.შ.).

## 3. Basic — Detail & Color

- [ ] **(მე)** Clarity — + UnsharpMask, − soft glow; 1.0 = no-op; scale-ს ითვალისწინებს.
- [ ] **(მე)** Dehaze — + შავ წერტილს ამუქებს/კონტრასტს↑, − პირიქით; 1.0 = no-op.
- [ ] **(მე)** Vibrance — მინავლებული ფერები მეტად იზრდება ვიდრე გაჯერებული.
- [ ] **(მე)** Color (საერთო გაჯერება) — 1.0 = no-op.
- [ ] **(მე)** Texture — + thresholded sharpen, − light smooth.
- [ ] **(მე)** Sharpen — >1 ამახვილებს, <1 აბუნდოვანებს (blur radius scale-ზე).
- [ ] **(მე)** Noise reduction — chroma median მაგრად, luma რბილად; 0 = off.
- [ ] **(შენ)** Clarity/Texture/Sharpen — არ „ჭრის“ არტეფაქტებს, ნოისს არ ამძაფრებს.
- [ ] **(შენ)** Denoise — ფერადი ნოისი მცირდება, დეტალი რჩება (ცოცხალი high-ISO ფოტო).

## 4. Auto (Photoshop-ისებრი)

- [ ] **(მე)** Auto level — თითო არხი ცალკე იჭიმება (cast-ს ასწორებს).
- [ ] **(მე)** Auto contrast — ერთი luminance stretch, ფერი უცვლელი.
- [ ] **(მე)** ორივე ურთიერთგამომრიცხავია (toggle logic).
- [ ] **(შენ)** ღილაკის ჩართვისას სურათი მართლა უმჯობესდება და accent-fill ეთიშება/ერთვება.

## 5. Effects

- [ ] **(მე)** Black & White — 0 = ფერადი, 1.0 = სრული grayscale (blend).
- [ ] **(მე)** Sepia — 0 = off, ramp თბილ ტონს აძლევს (shadow-brown/highlight-cream).
- [ ] **(მე)** Split tone — Highlights tone / Shadows tone, ± warm/cool, luminance mask-ით.
- [ ] **(მე)** Vignette — ± კუთხეები მუქდება/ნათდება; მასკა cache-დან, გეომეტრიაზეა მიბმული.
- [ ] **(მე)** Film grain — 0 = off, cell scale-ზეა (preview == save).
- [ ] **(შენ)** Grain — მარცვლის სიმსხო ბუნებრივია, ფერად speckle-ს არ ჰგავს.
- [ ] **(შენ)** Vignette — zoom/pan-ზე ცენტრზე დამაგრებული რჩება, კუთხეებში არ „ცურავს“.
- [ ] **(შენ)** Split tone — teal&orange look კანს არ ჭუჭყიანებს (midtones სუფთა).

## 6. Color mixer (HSL)

- [ ] **(მე)** 8 საჯერო ბენდი (Red/Orange/Yellow/Green/Aqua/Blue/Purple/Magenta) — თითო
      მხოლოდ თავის hue-ს ცვლის, მეზობლები რბილად გადაფარულია.
- [ ] **(მე)** Gold (hue/sat/shine) — hue+saturation gate: ღია/ნაცრისფერ ქვას არ ეხება.
- [ ] **(მე)** Skin (hue/sat/brightness) — მკაცრი hue, დაბალი sat gate (ღია კანიც შედის).
- [ ] **(მე)** `color_mixer_active` / `_mixer_sig` — ნეიტრალურზე no-op, cache signature სწორი.
- [ ] **(შენ)** Gold shine — მართლა მხოლოდ ოქროზე მუშაობს, კრემისფერ კედელზე არა.
- [ ] **(შენ)** Skin — მხოლოდ კანი მოძრაობს, უკანა თბილი კედელი არა.
- [ ] **(შენ)** ერთი ბენდი (მაგ. Blue) — ცაზე მუშაობს, ბალახზე არა.

## 7. Crop

- [ ] **(მე)** Ratio cards (1:1, 4:3, 3:2, 5:4) — box სწორ პროპორციაზე, ცენტრში.
- [ ] **(მე)** Segment: Free / Orig. (ფოტოს ratio) / Custom (დიალოგი).
- [ ] **(მე)** Social presets (4:5, 9:16, 16:9, 1.91) — სწორი ratio.
- [ ] **(მე)** Flip — width↔height და locked ratio იცვლება, image-ში ჯდება.
- [ ] **(მე)** `apply_crop` — box სწორად იჭრება; ზედმეტად პატარა/სრული = toast, no-op.
- [ ] **(მე)** Straighten — `_straighten_box` ცარიელ კუთხეებს არ ტოვებს; `_rotate_keep_size`.
- [ ] **(მე)** My sizes CRUD — add/edit/delete, `_save_state`, unique/format.
- [ ] **(მე)** crop-ის შემდეგ focus/text იშლება (source-px აღარ ჯდება).
- [ ] **(შენ)** Overlay dr– handles/edges/move-ის დრეგი, thirds grid, dim outside — ზუსტია.
- [ ] **(შენ)** rubber-band ახალი box, კურსორები (nw/se/...), straighten live preview.

## 8. Resize

- [ ] **(მე)** `_resize_target_for` — px (long side) და percent, aspect ინახება.
- [ ] **(მე)** Quality: soft (BICUBIC+blur) / normal (LANCZOS) / sharp (LANCZOS+UnsharpMask).
- [ ] **(მე)** Strength (light/medium/strong) — sharp/soft-ისთვის, normal-ს არ აქვს.
- [ ] **(მე)** `apply_resize` — ახალი ზომა, before ინახება (post=False), crop/focus reset.
- [ ] **(მე)** Whole-folder batch — ყველა ფაილი, ICC/EXIF გადააქვს, unique_path (overwrite არა).
- [ ] **(შენ)** live „→ W × H“ readout, unit chip (px/%), preset chips — UI-ში სწორი.
- [ ] **(შენ)** soft/normal/sharp — თვალით სხვაობა ჩანს (ვებ output-sharpening).

## 9. Perspective

- [x] **(მე)** Vertical (persp_v) / Horizontal (persp_h) — warp მიმართულება; 0 = no-op.
- [x] **(მე)** `apply_perspective_commit` — pixels ეცხობა, crop/focus/text/clone reset.
- [x] **(მე)** scale-free (preview view == full-res commit).
- [ ] **(შენ)** live warp fitted view-ზე ჩანს, შენობის ვერტიკალები სწორდება.

## 10. Heal & Clone

- [ ] **(მე)** `heal_region` — blemish clean neighbour-ით იფარება, colour-match.
- [ ] **(მე)** `heal_region(src=...)` — Alt+click-ით ხელით არჩეული წყარო, colour-match + flip.
- [ ] **(მე)** `clone_region` — locked offset, feather, opacity, flip (mirror).
- [ ] **(მე)** Brush size / Strength / Edge softness — მნიშვნელობებზე რეაქცია.
- [ ] **(მე)** Stroke = ერთი undo step; `_apply_heal_patch` before/after box.
- [ ] **(მე)** Aligned on/off — offset ინახება/თითო stroke-ზე ან re-anchor.
- [ ] **(შენ)** ხატვის დრეგი (dabs spacing), brush ring, clone source ring (Alt+click).
- [ ] **(შენ)** wheel / `[` `]` brush-ს ცვლის (და არ zoom-ავს).
- [ ] **(შენ)** heal შედეგი უნაკერო, colour-match ცოცხალ ფოტოზე ბუნებრივი.

## 11. Focus blur (depth of field)

- [ ] **(მე)** Circle — შიგნით მკვეთრი, გარეთ Gaussian blur; მასკა cache.
- [ ] **(მე)** Line (tilt-shift) — band მკვეთრი, კუთხე/სიგანე მუშაობს.
- [ ] **(მე)** Blur strength / feather — 0 = off, mask feather მხოლოდ outward.
- [ ] **(მე)** `_remove_focus` — off, ერთი undo step; source-px coords rel↔abs.
- [ ] **(შენ)** shape-ის დრეგი: move/resize/rotate handles, falloff ring — overlay ზუსტი.
- [ ] **(შენ)** blur ბუნებრივია, sharp→blur გადასვლა რბილი (feather).

## 12. Text & Watermark

- [ ] **(მე)** Add text — ერთი ახალი element, cascade down-right, `text_sel`.
- [ ] **(მე)** Delete text / Delete all — undoable, `text_sel` მართებული რჩება.
- [ ] **(მე)** `_apply_texts` / `text_extent` — position+size source-px, scale-ზე preview==save.
- [ ] **(მე)** Font / Size / Opacity / Colour / Shadow / Align — element-ზე იწერება.
- [ ] **(მე)** 3×3 position snap (`_place_text`) — margin-ით სწორ კუთხეში.
- [ ] **(მე)** გეომეტრიის ცვლილებაზე ტექსტი იშლება; ცარიელი box ≠ edit (undo არ იბიძგება).
- [ ] **(შენ)** ტექსტის დრეგი/resize handle, ბევრი ტექსტის select (topmost), placeholder hint.
- [ ] **(შენ)** Georgian ტექსტი (utf-8) სწორად იწერება და ჩანს (იხ. Tk encoding fix).
- [ ] **(შენ)** colorchooser (ნატიური დიალოგი) — ფერს იღებს.

## 13. Filters

- [ ] **(მე)** Create — მიმდინარე edit → named filter, `My filters`-ში.
- [ ] **(მე)** `_sanitize_filter_values` / `_coerce_filter_list` — hand-edited ფაილი უსაფრთხო.
- [ ] **(მე)** Groups — normalize (My filters first, Others last), unique names, fold state.
- [ ] **(მე)** Import / Export — round-trip (JSON in == out), group-less → Others.
- [ ] **(მე)** 8 built-in filter — `Edits`-ს ვალიდურად ქმნის, apply მოსალოდნელ ველებს დებს.
- [ ] **(მე)** `_filter_active` — live edit == filter values (accent highlight logic).
- [ ] **(მე)** `_apply_filter_values` — ყველა slider/auto სწორ მნიშვნელობაზე, ერთი undo.
- [ ] **(შენ)** Preview strip — თითო thumbnail ცოცხალ ფოტოზე სწორ look-ს აჩენს.
- [ ] **(შენ)** Manager: rename/refresh/delete/move, `…` menu, group fold — UI ქცევა.

## 14. Actions (macros)

- [ ] **(მე)** Record → step capture (edit coalesce, crop ცალკე), Stop → save.
- [ ] **(მე)** `_focus_to_rel` / `_focus_from_rel_size` — resolution-independent round-trip.
- [ ] **(მე)** `_resolve_action` — მხოლოდ ბოლო edit რჩება, crop focus-ს ასუფთავებს.
- [ ] **(მე)** `_apply_action_to_image` — სხვა ზომის ფოტოზეც სწორად replay-ს იძლევა.
- [ ] **(მე)** Batch to folder — ყველა ფაილი, unique_path, format/quality.
- [ ] **(მე)** `_sanitize_steps` — malformed ფაილი უსაფრთხოდ იფილტრება.
- [ ] **(შენ)** Record ღილაკი დარდისფერდება, step counter, replay ცოცხალ ფოტოზე იგივე შედეგი.

## 15. Save / Export

- [ ] **(მე)** `_write_save` — edits full-res-ზე ეცხობა, სწორი format/extension.
- [ ] **(მე)** Orientation EXIF → 1 (double-rotate არ ხდება).
- [ ] **(მე)** ICC/EXIF keep vs strip (keep_meta).
- [ ] **(მე)** sRGB convert (wide-gamut → sRGB, ICC re-tag).
- [ ] **(მე)** `unique_path` — არსებულ ფაილს არ გადააწერს (data-safety).
- [ ] **(მე)** JPEG/PNG/WEBP + quality; PNG-ს quality არ აქვს.
- [ ] **(მე)** quick_save unarmed → Save-as დიალოგი; armed → ჩუმად წერს.
- [ ] **(შენ)** Save-as დიალოგი: folder browse, name+ext suffix, chips, checkboxes — UI.
- [ ] **(შენ)** შენახული ფაილი სხვა viewer-ში ფერით/ორიენტაციით სწორია.

## 16. Navigation & Culling

- [ ] **(მე)** prev/next/first/last + wrap-around ლოგიკა.
- [ ] **(მე)** `_has_unsaved_edits` / `_has_any_edits` — guard სწორად ითვლის.
- [ ] **(მე)** Cull move (`_fs_move` / `_move_current_to` / `_drop_from_list` / `_add_to_list`).
- [ ] **(მე)** `_sibling_folder` — შემდეგი/წინა folder ფოტოებით.
- [ ] **(მე)** Undo/redo ყველა kind-ზე (move / edit / heal).
- [ ] **(შენ)** ←/→ browse, ↑/↓ cull (panel დახურული), edit ველში კლავიშები არ ერევა.
- [ ] **(შენ)** Edge dialog (wrap/sibling + remember), cull confirm, unsaved-edit dialog.
- [ ] **(შენ)** Restore original — confirm-ის შემდეგ ორიგინალი ბრუნდება.
- [ ] **(შენ)** Cull ცოცხლად: keep/reject ღილაკები, folder tint, „Ctrl+Z“ toast.

## 17. Global UI

- [ ] **(მე)** Storage: `save_json` atomic, `unique_path` — headless (STATE_FILE redirect!).
- [ ] **(მე)** i18n — Georgian translation-ში გასაღებები არ აკლია, `t()` fallback.
- [ ] **(შენ)** Histogram — ცოცხლად ედიტს მიჰყვება; Show/hide setting.
- [ ] **(შენ)** Compare (before/after) — crop/heal-ის შემდეგ „before“ სწორად ასწორებს.
- [ ] **(შენ)** Zoom / pan / hand tool / fit — გლუვი, DPI-ზე სწორი.
- [ ] **(შენ)** Thumbnail strip — virtualization (5000+ ფაილი), sorting ↑/↓.
- [ ] **(შენ)** Settings window (General/Export/Culling/About) — wired controls მუშაობს.
- [ ] **(შენ)** Metadata window (top-bar info) — ფოტოს metadata სწორად აჩვენებს.
- [ ] **(შენ)** Loading overlay — გრძელი load-ის დროს blocking „გთხოვთ დაელოდოთ“.
- [ ] **(შენ)** Slider lag — async render, coalescing გლუვია დიდ ფოტოზე.

---

## რას ვგეგმავ (მე)

ერთი `tests/` პაკეტი: (1) სუფთა imaging ფუნქციების unit-ტესტები (ყველა ეფექტი —
მიმართულება, no-op, cache==flat), (2) filters/actions JSON round-trip + resolution
independence, (3) save pipeline (orientation/ICC/unique_path), headless, STATE_FILE
temp-ში გადამისამართებული. „(შენ)“ პუნქტები რჩება ხელით შესამოწმებელი.
