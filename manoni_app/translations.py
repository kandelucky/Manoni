"""Language packs for Manoni.

The strings written in the code are ENGLISH (the app's original language). Each
pack maps an English source string (exactly as written in the code) to its
translation. Keep a key character-for-character identical to the source string
that t() is called with — a mismatch isn't an error, the string just falls back
to English. Importing this module registers every pack with i18n.

To add a language: copy CATALOG_KA, translate the values, register it below, and
add its (code, native_name) to i18n.LANGUAGES.
"""

from . import i18n

# English source  ->  Georgian. (English itself is the default; it needs no
# pack — t() returns the source unchanged.)
CATALOG_KA = {
    # --- "Language" menu entry --------------------------------------------
    "Language": "ენა",
    "Settings": "პარამეტრები",

    # --- Sidebar view modes (manoni.py VIEW_MENU) -------------------------
    "Large icons": "დიდი ხატულები",
    "Medium icons": "საშუალო ხატულები",
    "Small icons": "პატარა ხატულები",
    "List": "სია",
    "Icons": "ხატულები",

    # --- Toolbar / window chrome ------------------------------------------
    "Open folder": "ფოლდერის გახსნა",
    "Hand tool — drag to pan the photo": "ხელის ხელსაწყო — გადაათრიე სურათი",
    "Compare before / after — click to split, hold to see the original":
        "შედარება იყო / არის — დააწკაპუნე ხაზისთვის, ეჭირე ორიგინალის სანახავად",
    "Before": "იყო",
    "After": "არის",
    "Hold to see the original — press for before, release for after":
        "ეჭირე ორიგინალის სანახავად — დააჭირე იყო, აუშვი არის",
    "Undo (Ctrl+Z)": "დაბრუნება (Ctrl+Z)",
    "Redo (Ctrl+Y)": "გამეორება (Ctrl+Y)",
    "Menu": "მენიუ",
    "Keep (keeper)": "შენახვა (keeper)",
    "Reject": "გადაგდება (reject)",
    "Sorting folders": "დახარისხების ფოლდერები",
    "Culling — Help": "გადარჩევა — დახმარება",
    "Save as…": "შენახვა როგორც…",
    "Up a folder": "ზემოთ ფოლდერი",
    "No folder open": "ფოლდერი არ არის გახსნილი",
    "Smaller thumbnails": "პატარა თამბნეილები",
    "Larger thumbnails": "დიდი თამბნეილები",
    "Grid view — see many photos at once (for culling)":
        "ბადე — ბევრი ფოტო ერთად (გადასარჩევად)",
    "No photos to show": "საჩვენებელი ფოტო არ არის",
    # --- Grid view drop zones (drag photos onto Good / Bad) ---------------
    "Good": "კარგი",
    "Bad": "ცუდი",
    "(set a folder)": "(მიუთითე ფოლდერი)",
    "1 photo": "1 ფოტო",
    "{n} photos": "{n} ფოტო",
    "Moved {n} → {name}  ·  Ctrl+Z": "{n} გადატანილია → {name}  ·  Ctrl+Z",
    "Couldn't open the folder: {e}": "ფოლდერი ვერ გაიხსნა: {e}",

    # --- Photo navigation (browser.py) ------------------------------------
    "First": "პირველი",
    "Previous": "წინა",
    "Next": "შემდეგი",
    "Last": "ბოლო",
    "Rotate left": "მარცხნივ ამოტრიალება",
    "Rotate right": "მარჯვნივ ამოტრიალება",
    "Zoom out": "დაპატარავება",
    "Zoom in": "გადიდება",
    "No photos found": "ფოტოები ვერ მოიძებნა",
    "Please wait…": "დაელოდეთ…",
    "Loading photos…": "სურათები იტვირთება…",

    # --- Edit panel: sections, sliders, auto tone (editpanel.py) ----------
    "Heal & Clone": "შეკეთება & კლონი",
    "Focus blur": "ფოკუსის ბლური",
    "Effects": "ეფექტები",
    "Filters": "ფილტრები",

    # --- Focus blur tool (focus.py) ---------------------------------------
    "Blur": "ბლური",
    "Circle": "წრე",
    "Line": "ხაზი",
    "Drag the circle to set the focus; the edge resizes it. Sharp inside, blurred outside.":
        "გადაათრიე წრე ფოკუსისთვის; კიდე ზომას ცვლის. შიგნით მკვეთრია, გარეთ — ბლური.",
    "Drag the band to set the focus; an edge changes its width, the end dot rotates it. Sharp in the band, blurred outside.":
        "გადაათრიე ზოლი ფოკუსისთვის; კიდე სიგანეს ცვლის, ბოლო წერტილი — კუთხეს. ზოლში მკვეთრია, გარეთ — ბლური.",
    "Blur strength": "ბლურის სიძლიერე",
    "Transition softness": "გადასვლის სიფაფუკე",
    "Remove blur": "ბლურის მოშორება",
    "Turn the focus blur off": "ფოკუსის ბლურის გამორთვა",
    "Auto level": "ავტო ლეველი",
    "Auto-correct color balance (each channel stretched separately)":
        "ფერის ბალანსის ავტო-სწორება (თითო არხი ცალკე იჭიმება)",
    "Auto contrast": "ავტო კონტრასტი",
    "Auto-correct contrast (color stays unchanged)":
        "კონტრასტის ავტო-სწორება (ფერი უცვლელი რჩება)",
    "White balance": "თეთრის ბალანსი",
    "Temperature": "სითბო",
    "Tint": "ტინტი",
    "Tone": "ტონი",
    "Exposure": "ექსპოზიცია",
    "Contrast": "კონტრასტი",
    "Highlights": "ნათელები",
    "Shadows": "ჩრდილები",
    "Whites": "თეთრები",
    "Blacks": "შავები",
    "Detail & Color": "დეტალი და ფერი",
    "Clarity": "სიცხადე",
    "Vibrance": "სიხასხასე",
    "Color": "ფერი",
    "Texture": "ტექსტურა",
    "Sharpen": "სიმკვეთრე",
    # --- Color mixer (HSL) section (editpanel.py) -------------------------
    "Color mixer": "ფერების მიქსერი",
    "Colors": "ფერები",
    "Saturation": "გაჯერება",
    "Red": "წითელი",
    "Orange": "ნარინჯისფერი",
    "Yellow": "ყვითელი",
    "Green": "მწვანე",
    "Aqua": "ცისფერი",
    "Blue": "ლურჯი",
    "Purple": "იისფერი",
    "Magenta": "მაჯენტა",
    "Gold": "ოქრო",
    "Gold hue": "ოქროს ელფერი",
    "Gold saturation": "ოქროს გაჯერება",
    "Gold shine": "ოქროს ბზინვარება",
    "Skin": "კანი",
    "Skin hue": "კანის ელფერი",
    "Skin saturation": "კანის გაჯერება",
    "Skin brightness": "კანის სიკაშკაშე",
    "Black & White": "შავ-თეთრი",
    "Sepia": "სეპია",
    "Vignette": "ვინიეტი",
    "Film grain": "ფირის მარცვალი",
    "Soon": "მალე",
    "Open / collapse the panel": "პანელის გახსნა / დაკეცვა",
    "Heal": "შეკეთება",
    "Save": "შენახვა",
    "Reset this slider": "სლაიდერის განულება",
    "Clear all": "გასუფთავება",
    "Reset all sliders": "ყველა სლაიდერის განულება",

    # --- Filters manager (filters.py) -------------------------------------
    "Save the current edit as a filter, or add ready-made filters from a file.":
        "შენ შეგიძლია მიმდინარე ედიტი ფილტრად შეინახო, ან მზა ფილტრები ფაილიდან ჩამოამატო.",
    "Saved filters: {n}": "შენახული ფილტრები: {n}",
    "Create filter": "ფილტრის შექმნა",
    "Saves the current slider values as a filter":
        "მიმდინარე სლაიდერების მნიშვნელობებს ფილტრად შეინახავს",
    "Edit": "რედაქტირება",
    "Rename / refresh / delete saved filters":
        "შენახული ფილტრების გადარქმევა / განახლება / წაშლა",
    "Import": "იმპორტი",
    "Load filters from a .json file": "ფილტრების ჩამოტვირთვა .json ფაილიდან",
    "Export": "ექსპორტი",
    "Save filters to a .json file to share":
        "ფილტრების შენახვა .json ფაილში გასაზიარებლად",
    "My filter": "ჩემი ფილტრი",
    "New filter": "ახალი ფილტრი",
    "Filter name": "ფილტრის სახელი",
    "Filter saved: {name}": "ფილტრი შენახულია: {name}",
    "No filters saved yet": "ჯერ ფილტრი არ შენახულა",
    "Edit filters": "ფილტრების რედაქტირება",
    "No filters left": "ფილტრები აღარ არის",
    "Refresh from current edit": "მიმდინარე ედიტით განახლება",
    "Delete": "წაშლა",
    "Rename": "გადარქმევა",
    "Filter refreshed: {name}": "ფილტრი განახლდა: {name}",
    "Import filters": "ფილტრების იმპორტი",
    "Filter file": "ფილტრის ფაილი",
    "All files": "ყველა ფაილი",
    "Added {n} filter(s)": "დაიმატა {n} ფილტრი",
    "No filters found in the file": "ფაილში ფილტრები ვერ მოიძებნა",
    "Export filters": "ფილტრების ექსპორტი",
    "All in one file": "ყველას ერთ ფაილში",
    "Save filters": "ფილტრების შენახვა",
    "Exported {n} filter(s)": "ექსპორტი დასრულდა: {n} ფილტრი",
    "Could not write the file": "ფაილის ჩაწერა ვერ მოხერხდა",
    "Could not save filters": "ფილტრების შენახვა ვერ მოხერხდა",
    "Close": "დახურვა",

    # --- Filter preview strip (filters.py) --------------------------------
    "Original": "ორიგინალი",
    "Apply filter: {name}": "ფილტრის გამოყენება: {name}",
    "Remove the filter (show the original)":
        "ფილტრის მოხსნა (ორიგინალის ჩვენება)",

    # --- Built-in filter names (filters.py BUILTIN_FILTERS) ---------------
    # "Clarendon" is a proper name → left in English (falls back to the source).
    "Vivid": "მკვეთრი",
    "Warm": "თბილი",
    "Cool": "ცივი",
    "Vintage": "ვინტაჟი",
    "Matte": "მქრქალი",
    "Mono": "მონო",

    # --- Filter group names (filters.py reserved groups) ------------------
    "Standard": "სტანდარტული",
    "My filters": "ჩემი ფილტრები",
    "Others": "დანარჩენი",

    # --- Filter groups manager (filters.py) -------------------------------
    "New group": "ახალი ჯგუფი",
    "New group…": "ახალი ჯგუფი…",
    "Group name": "ჯგუფის სახელი",
    "Group": "ჯგუფი",
    "Rename group": "ჯგუფის გადარქმევა",
    "Delete group": "ჯგუფის წაშლა",
    "Export group": "ჯგუფის ექსპორტი",
    "Move to group": "ჯგუფში გადატანა",
    "No filters in this group": "ამ ჯგუფში ფილტრები არ არის",
    "Please confirm": "დაადასტურე",
    "Delete the group “{name}” and its {n} filter(s)?":
        "წავშალო ჯგუფი „{name}“ და მისი {n} ფილტრი?",
    "OK": "კარგი",

    # --- Actions / macros (actions.py) ------------------------------------
    "Actions": "მოქმედებები",
    "Record your edits as an action, then play it on any open photo.":
        "ჩაიწერე შენი ედიტები მოქმედებად, მერე დააკარი ნებისმიერ ღია სურათს.",
    "Record action": "მოქმედების ჩაწერა",
    "Stop recording": "ჩაწერის შეჩერება",
    "Recording… do your edits, then press Stop":
        "მიმდინარეობს ჩაწერა… გააკეთე ედიტები, მერე დააჭირე „შეჩერებას“",
    "Recording… {n} step(s)": "ჩაწერა… {n} ნაბიჯი",
    "Nothing was recorded": "არაფერი ჩაიწერა",
    "My action": "ჩემი მოქმედება",
    "New action": "ახალი მოქმედება",
    "Action name": "მოქმედების სახელი",
    "Action saved: {name}": "მოქმედება შენახულია: {name}",
    "Saved actions: {n}": "შენახული მოქმედებები: {n}",
    "No actions yet": "ჯერ მოქმედებები არ არის",
    "Play this action": "ამ მოქმედების დაკვრა",
    "Action applied: {name}": "მოქმედება დადებულია: {name}",
    "Stop recording first": "ჯერ შეაჩერე ჩაწერა",
    "Apply to the whole folder": "მთელ ფოლდერზე დადება",
    "Apply to whole folder": "მთელ ფოლდერზე დადება",
    "Apply this action to all {n} photos and save copies.":
        "დაადე ეს მოქმედება ფოლდერის ყველა ({n}) სურათს და შეინახე ასლები.",
    "Open a folder first": "ჯერ გახსენი ფოლდერი",
    "Output folder": "გამოსატანი ფოლდერი",
    "Apply": "დადება",
    "Applying to folder… {i}/{n}": "ფოლდერზე დადება… {i}/{n}",
    "Could not create the output folder": "გამოსატანი ფოლდერი ვერ შეიქმნა",
    "Done — {ok} saved, {fail} failed  ·  {dir}":
        "დასრულდა — {ok} შენახულია, {fail} ჩავარდა  ·  {dir}",
    "Could not save actions": "მოქმედებების შენახვა ვერ მოხერხდა",

    # --- Crop tool (crop.py) ----------------------------------------------
    "Free": "თავისუფ.",
    "Original": "ორიგინ.",
    "Custom": "საკუთარი",
    "IG Portrait 4:5": "IG პორტრ. 4:5",
    "Drag the corners; pick a shape or social network":
        "ჩავათრიე კუთხეები; აირჩიე ფორმა ან სოც. ქსელი",
    "Shape": "ფორმა",
    "Straighten": "გასწორება",
    "Angle": "კუთხე",
    "Tilt to level the horizon (the crop trims the corners)":
        "დახარე ჰორიზონტის გასასწორებლად (მოჭრა კუთხეებს მოაჭრის)",
    "Social networks": "სოციალური ქსელები",
    "⇄ Flip (3:4 ⇄ 4:3)": "⇄ გადატრიალება (3:4 ⇄ 4:3)",
    "Rotate the selection by 90°": "მონიშვნის 90°-ით გადატრიალება",
    "Crop": "მოჭრა",
    "Cancel": "გაუქმება",
    "Reset the selection to the whole image": "მონიშვნის სრულ სურათზე დაბრუნება",
    "Cust.": "საკ.",
    "Custom size": "საკუთარი ზომა",
    "Custom ratio": "საკუთარი პროპორცია",
    "Width : Height  (e.g. 4:5 or 1200:800)":
        "სიგანე : სიმაღლე  (მაგ. 4:5 ან 1200:800)",
    "Enter two positive numbers": "შეიყვანე ორი დადებითი რიცხვი",
    "Numbers must be positive": "რიცხვები დადებითი უნდა იყოს",
    "Select": "არჩევა",
    "The crop area is too small": "მოსაჭრელი არე ძალიან პატარაა",
    "The whole image is selected — nothing changes":
        "მთელი სურათია მონიშნული — არაფერი იცვლება",
    "Cropped → {w}×{h}px  ·  Save to write it to a file":
        "მოიჭრა → {w}×{h}px  ·  შენახვა ფაილში ჩასაწერად",
    "My sizes": "შენი ზომები",
    "Orig.": "ორიგ.",
    "Instagram portrait": "Instagram პორტრეტი",
    "Post · vertical": "პოსტი · ვერტიკალური",
    "Full screen": "სრული ეკრანი",
    "Horizontal": "ჰორიზონტალური",
    "Share banner": "გაზიარების ბანერი",
    "Your size": "შენი ზომა",
    "Add your size to the list": "შენი საზომის დამატება სიაში",
    "No sizes yet": "ჯერ ზომები არ გაქვს",
    "Create size": "ზომის შექმნა",
    "Edit size": "ზომის რედაქტირება",
    "Custom shape": "საკუთარი ფორმა",
    "Name it and set width : height (pixels or a ratio, e.g. 4:5).":
        "დაარქვი სახელი და მიუთითე სიგანე : სიმაღლე (პიქსელი ან პროპორცია, მაგ. 4:5).",
    "Size — Width : Height": "ზომა — სიგანე : სიმაღლე",

    # --- Resize tool (resize.py) ------------------------------------------
    "Resize": "ზომის შეცვლა",
    "Size": "ზომა",
    "Long side": "გრძელი გვერდი",
    "Percent": "პროცენტი",
    "Current: {w} × {h}": "ამჟამად: {w} × {h}",
    "The original stays untouched — Save writes the resized copy.":
        "ორიგინალი ხელუხლებელია — შენახვა ჩაწერს შეცვლილ ასლს.",
    "Enter a valid size": "შეიყვანე სწორი ზომა",
    "That's already the current size": "ეს უკვე მიმდინარე ზომაა",
    "Pixels": "პიქსელები",
    "Soft": "რბილი",
    "Normal": "ნორმალური",
    "Sharp": "მკვეთრი",
    "Light": "მსუბუქი",
    "Medium": "საშუალო",
    "Strong": "ძლიერი",
    "Soft = smoother · Sharp adds web output-sharpening.":
        "რბილი = უფრო გლუვი · მკვეთრი ამატებს ვების გამკვეთვას.",
    "Resized → {w}×{h}px  ·  Save to write it to a file":
        "ზომა შეიცვალა → {w}×{h}px  ·  შენახვა ფაილში ჩასაწერად",
    "Whole folder": "მთელი ფოლდერი",
    "Resize every photo in the folder with the size above. "
    "Originals are untouched; the copies go to a new folder.":
        "ფოლდერის ყველა ფოტოს შეუცვლის ზომას ზემოთ მითითებულით. "
        "ორიგინალები ხელუხლებელია; ასლები ახალ ფოლდერში შეინახება.",
    "Resize the whole folder": "მთელი ფოლდერის რესიზე",
    "Resize whole folder": "მთელი ფოლდერის რესიზე",
    "Resize all {n} photos in the folder and save the copies.":
        "შეუცვალე ზომა ფოლდერის ყველა ({n}) ფოტოს და შეინახე ასლები.",
    "Resizing folder… {i}/{n}": "ფოლდერის რესიზე… {i}/{n}",
    "Done — {ok} resized, {fail} failed  ·  {dir}":
        "დასრულდა — {ok} შეიცვალა, {fail} ჩავარდა  ·  {dir}",

    # --- Retouch / heal tool (heal.py) ------------------------------------
    "Auto heal": "ავტო შეკეთება",
    "Clone": "კლონი",
    "Aligned": "თანხვედრილი",
    "Mirror": "სარკისებური",
    "Brush size": "ფუნჯის ზომა",
    "Strength": "სიძლიერე",
    "Edge softness": "კიდის სიფაფუკე",
    "Ctrl+Z — undo the last action": "Ctrl+Z — ბოლო მოქმედების გაუქმება",
    "Alt+click — pick a source; then paint an exact copy. The wheel or [ ] changes the brush size.":
        "Alt+დააწკაპე — წყაროს არჩევა; მერე ხატე ზუსტი ასლი. ბორბალი ან [ ] ფუნჯის ზომას ცვლის.",
    "Click or drag over a blemish — I erase it with a copy of nearby clean background. The wheel or [ ] changes the brush size.":
        "დააწკაპე ან გადაუსვი ლაქას — ვშლი მახლობელი სუფთა ფონის ასლით. ბორბალი ან [ ] ფუნჯის ზომას ცვლის.",
    "Source picked — now paint the copy": "წყარო არჩეულია — ახლა ხატე ასლი",
    "First Alt+click a source": "ჯერ Alt+დააწკაპე წყაროზე",
    "Can't undo — a different image is open":
        "გაუქმება შეუძლებელია — სხვა სურათია",

    # --- Navigation / cull / undo dialogs (nav.py) ------------------------
    "End of the folder": "ფოლდერის ბოლოა",
    "Start of the folder": "ფოლდერის დასაწყისია",
    # Folder-edge chooser (←/→ past the edge)
    "You're on the last photo": "ბოლო ფოტოზე ხარ",
    "You're on the first photo": "პირველ ფოტოზე ხარ",
    "Where should the arrow keys go next?":
        "სად გადავიდეს ისრები შემდეგ?",
    "Go to the first photo": "გადადი პირველ ფოტოზე",
    "Go to the last photo": "გადადი ბოლო ფოტოზე",
    "Go to the next folder": "გადადი მომდევნო ფოლდერში",
    "Go to the previous folder": "გადადი წინა ფოლდერში",
    "Remember my choice": "დაიმახსოვრე ჩემი არჩევანი",
    "Back to the first photo": "დაბრუნდა პირველ ფოტოზე",
    "Jumped to the last photo": "გადახტა ბოლო ფოტოზე",
    "No more folders this way": "ამ მხარეს ფოლდერი აღარაა",
    "Folder: {name}": "ფოლდერი: {name}",
    # Folder-edge setting (settings.py · Culling tab)
    "At the end of the folder": "ფოლდერის ბოლოს",
    "When you pass the last photo": "როცა ბოლო ფოტოს გასცდები",
    "← / → past the edge of the folder.": "← / → ფოლდერის კიდის მიღმა.",
    "Ask": "მკითხე",
    "First photo": "პირველი ფოტო",
    "Next folder": "მომდევნო ფოლდერი",
    "“Ask” pops a small chooser each time you reach the edge. “First photo” "
    "loops back; “Next folder” opens the next folder that has photos.":
        "„მკითხე“ ყოველ ჯერზე პატარა ფანჯარას აჩენს კიდესთან. „პირველი ფოტო“ "
        "თავში აბრუნებს; „მომდევნო ფოლდერი“ შემდეგ ფოლდერს ხსნის, რომელშიც ფოტოა.",
    "Save?": "შენახვა?",
    "The image has changed": "სურათი შეცვლილია",
    "{fname} — save a copy to _edited?":
        "{fname} — შევინახო კოპია _edited-ში?",
    "Don't save": "არ შევინახო",
    "Set the sorting folders first  ·  ⚙ Settings":
        "ჯერ მიუთითე დახარისხების ფოლდერები  ·  ⚙ პარამეტრები",
    "Kept → {name}  ·  Ctrl+Z": "შენახულია → {name}  ·  Ctrl+Z",
    "Rejected → {name}  ·  Ctrl+Z": "გადაგდებულია → {name}  ·  Ctrl+Z",
    "Set where kept and rejected photos go. Until both are set, the buttons don't work.":
        "მიუთითე სად გადავიდეს დატოვებული და გადაგდებული ფოტოები. სანამ ორივე არ მითითებულა, ღილაკები არ მუშაობს.",
    "✓ Keep (keeper) — photos you keep":
        "✓ შენახვა (keeper) — დატოვებული ფოტოები",
    "✗ Reject — photos you discard":
        "✗ გადაგდება (reject) — გადაგდებული ფოტოები",
    "Sorting folders saved": "დახარისხების ფოლდერები შენახულია",
    "Folders incomplete — culling doesn't work yet":
        "ფოლდერები არასრულია — გადარჩევა ჯერ არ მუშაობს",
    "Culling photos": "ფოტოების გადარჩევა (culling)",
    "You browse the photos and sort each into two folders — keep and discard.":
        "ათვალიერებ ფოტოებს და თითოეულს ანაწილებ ორ ფოლდერში — დასატოვებელი და გადასაგდები.",
    "Moves the current photo to the keep folder.":
        "მიმდინარე ფოტოს გადააქვს დასატოვებელ ფოლდერში.",
    "Moves the current photo to the discard folder.":
        "მიმდინარე ფოტოს გადააქვს გადასაგდებ ფოლდერში.",
    "Settings": "პარამეტრები",
    "Set these two folders — until you do, the buttons don't work.":
        "მიუთითე ეს ორი ფოლდერი — სანამ არ მიუთითებ, ღილაკები არ მუშაობს.",
    "Ctrl+Z undoes any move.": "Ctrl+Z აბრუნებს ნებისმიერ გადატანას.",
    "Got it": "გასაგებია",
    "Nothing to undo": "გასაუქმებელი არაფერია",
    "Nothing to redo": "გასამეორებელი არაფერია",
    "Error: {e}": "შეცდომა: {e}",
    "Restored: {name}": "დაბრუნდა: {name}",
    "Moved: {name}": "გადატანილია: {name}",
    "End of folder": "ფოლდერის ბოლოა",
    "Start of folder": "ფოლდერის დასაწყისია",
    "Can't undo the edit — a different folder is open":
        "რედაქტირების გაუქმება შეუძლებელია — სხვა ფოლდერია",
    "Can't undo the edit — the file no longer exists":
        "რედაქტირების გაუქმება შეუძლებელია — ფაილი აღარ არსებობს",

    # --- Save-as dialog (saving.py) ---------------------------------------
    "Save as": "შენახვა როგორც",
    "Open an image first": "ჯერ გახსენი სურათი",
    "Folder": "საქაღალდე",
    "Choose a folder": "აირჩიე საქაღალდე",
    "Name": "სახელი",
    "Quality": "ხარისხი",
    "Use this config for quick save":
        "გამოვიყენე ეს კონფიგი სწრაფი შენახვისთვის",
    "Convert colours to sRGB (best for web)":
        "ფერების sRGB-ში გადაყვანა (ვებისთვის საუკეთესო)",
    "Format": "ფორმატი",
    "Saved → {name}": "შენახულია → {name}",

    # --- About / Authors dialog (about.py) --------------------------------
    "About Manoni": "Manoni-ს შესახებ",
    "A fast, simple dark photo browser and culler.":
        "სწრაფი, მარტივი მუქი ფოტო ბრაუზერი და გადამრჩევი.",
    "Author": "ავტორი",
    "Written in Python": "დაწერილია Python-ზე",
    "Built with": "გამოყენებული ტექნოლოგიები",
    "Links": "ბმულები",
    "Buy me a coffee": "გამიმასპინძლდი ყავით",

    # --- Language menu + "Add your language" studio (chrome.py) ------------
    "Add your language": "დაამატე შენი ენა",
    "Manoni can speak any language. Here's how:\n"
    "1. Generate a template file — it lists every English text.\n"
    "2. Open it in any text editor and fill in your translations.\n"
    "3. Import the finished file — your language appears in the menu.":
        "მანონი ნებისმიერ ენაზე ალაპარაკდება. აი როგორ:\n"
        "1. დააგენერირე შაბლონის ფაილი — შიგ ყველა ინგლისური ტექსტია.\n"
        "2. გახსენი ის ნებისმიერ ტექსტურ რედაქტორში და თარგმნე.\n"
        "3. დააიმპორტირე მზა ფაილი — შენი ენა მენიუში გამოჩნდება.",
    "Generate template file": "შაბლონის ფაილის გენერაცია",
    "Save a .json file with every text to translate":
        "შეინახე .json ფაილი ყველა სათარგმნი ტექსტით",
    "Import a language": "ენის იმპორტი",
    "Load a finished .json translation and install it":
        "ჩატვირთე მზა .json თარგმანი და დააინსტალირე",
    "Export a language": "ენის ექსპორტი",
    "Save an installed language to a .json file to share":
        "შეინახე დაინსტალირებული ენა .json ფაილში გასაზიარებლად",
    "Save template": "შაბლონის შენახვა",
    "Language file": "ენის ფაილი",
    "Template saved → {name}": "შაბლონი შენახულია → {name}",
    "That isn't a valid language file": "ეს არ არის სწორი ენის ფაილი",
    "That language code is reserved": "ეს ენის კოდი დაცულია",
    "Language added: {name}": "ენა დაემატა: {name}",
    "No languages to export yet": "ჯერ საექსპორტო ენა არ არის",
    "Exported → {name}": "ექსპორტი დასრულდა → {name}",

    # --- Metadata: keep/strip toggle + photo info window (metadata.py) -----
    "Photo info (metadata)": "ფოტოს ინფო (მეტამონაცემები)",
    "Keep metadata (camera info, GPS, colour profile)":
        "მეტამონაცემის შენახვა (კამერა, GPS, ფერის პროფილი)",
    "Photo info": "ფოტოს ინფო",
    "File": "ფაილი",
    "Dimensions": "ზომები",
    "Megapixels": "მეგაპიქსელი",
    "Colour mode": "ფერის რეჟიმი",
    "File size": "ფაილის ზომა",
    "Colour profile": "ფერის პროფილი",
    "Profile": "პროფილი",
    "Size": "ზომა",
    "embedded": "ჩაშენებული",
    "Camera": "კამერა",
    "Make": "მწარმოებელი",
    "Model": "მოდელი",
    "Lens": "ობიექტივი",
    "Software": "პროგრამა",
    "Capture": "გადაღება",
    "Date taken": "გადაღების თარიღი",
    "Shutter": "ჩამკეტი",
    "Aperture": "დიაფრაგმა",
    "Focal length": "ფოკუსური მანძილი",
    "Exposure bias": "ექსპოზიციის კომპენსაცია",
    "Location": "მდებარეობა",
    "Coordinates": "კოორდინატები",
    "Altitude": "სიმაღლე",
    "This photo has no embedded metadata (no colour profile or EXIF).":
        "ამ ფოტოს არ აქვს ჩაშენებული მეტამონაცემი (არც ფერის პროფილი, არც EXIF).",
    "Delete metadata": "წაშალე მონაცემები",
    "Permanently remove the colour profile and all EXIF (including GPS location) "
    "from “{name}”?\n\nThe pixels are kept exactly; this can't be undone.":
        "სამუდამოდ წავშალო ფერის პროფილი და მთელი EXIF (GPS მდებარეობის ჩათვლით) "
        "ფაილიდან „{name}“?\n\nპიქსელები უცვლელად რჩება; ეს შეუქცევადია.",
    "Metadata removed → {name}": "მონაცემები წაშლილია → {name}",
}

# Register the built-in Georgian pack, then any user-imported packs on disk (so a
# language added via the studio survives the relaunch a language switch triggers).
# English = default, no pack needed.
i18n.register("ka", CATALOG_KA)

from .config import LANG_DIR  # noqa: E402 — imported here to avoid a cycle at top
i18n.load_user_packs(LANG_DIR)
