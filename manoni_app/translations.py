"""Language packs for Manoni.

Each pack maps a GEORGIAN source string (exactly as written in the code) to its
translation. Keep a key character-for-character identical to the source string
that t() is called with — a mismatch isn't an error, the string just falls back
to Georgian. Importing this module registers every pack with i18n.

To add a language: copy CATALOG_EN, translate the values, register it below, and
add its (code, native_name) to i18n.LANGUAGES.
"""

from . import i18n

# Georgian source  ->  English. (Georgian itself is the default; it needs no
# pack — t() returns the source unchanged.)
CATALOG_EN = {
    # --- "Language" menu entry --------------------------------------------
    "ენა": "Language",

    # --- Sidebar view modes (manoni.py VIEW_MENU) -------------------------
    "დიდი ხატულები": "Large icons",
    "საშუალო ხატულები": "Medium icons",
    "პატარა ხატულები": "Small icons",
    "სია": "List",
    "ხატულები": "Icons",

    # --- Toolbar / window chrome ------------------------------------------
    "ფოლდერის გახსნა": "Open folder",
    "დაბრუნება (Ctrl+Z)": "Undo (Ctrl+Z)",
    "გამეორება (Ctrl+Y)": "Redo (Ctrl+Y)",
    "მენიუ": "Menu",
    "შენახვა (keeper)": "Keep (keeper)",
    "გადაგდება (reject)": "Reject",
    "დახარისხების ფოლდერები": "Sorting folders",
    "გადარჩევა — დახმარება": "Culling — Help",
    "შენახვა როგორც…": "Save as…",
    "ზემოთ ფოლდერი": "Up a folder",
    "ფოლდერი არ არის გახსნილი": "No folder open",
    "პატარა თამბნეილები": "Smaller thumbnails",
    "დიდი თამბნეილები": "Larger thumbnails",

    # --- Photo navigation (browser.py) ------------------------------------
    "პირველი": "First",
    "წინა": "Previous",
    "შემდეგი": "Next",
    "ბოლო": "Last",
    "მარცხნივ ამოტრიალება": "Rotate left",
    "მარჯვნივ ამოტრიალება": "Rotate right",
    "დაპატარავება": "Zoom out",
    "გადიდება": "Zoom in",
    "ფოტოები ვერ მოიძებნა": "No photos found",

    # --- Edit panel: sections, sliders, auto tone (editpanel.py) ----------
    "შეკეთება & კლონი": "Heal & Clone",
    "ფოკუსის ბლური": "Focus blur",
    "ეფექტები": "Effects",
    "ფილტრები": "Filters",

    # --- Focus blur tool (focus.py) ---------------------------------------
    "ბლური": "Blur",
    "გადაათრიე წრე ფოკუსისთვის; კიდე ზომას ცვლის. "
    "შიგნით მკვეთრია, გარეთ — ბლური.":
        "Drag the circle to set the focus; the edge resizes it. "
        "Sharp inside, blurred outside.",
    "ბლურის სიძლიერე": "Blur strength",
    "გადასვლის სიფაფუკე": "Transition softness",
    "ბლურის მოშორება": "Remove blur",
    "ფოკუსის ბლურის გამორთვა": "Turn the focus blur off",
    "ავტო ლეველი": "Auto level",
    "ფერის ბალანსის ავტო-სწორება (თითო არხი ცალკე იჭიმება)":
        "Auto-correct color balance (each channel stretched separately)",
    "ავტო კონტრასტი": "Auto contrast",
    "კონტრასტის ავტო-სწორება (ფერი უცვლელი რჩება)":
        "Auto-correct contrast (color stays unchanged)",
    "თეთრის ბალანსი": "White balance",
    "სითბო": "Temperature",
    "ტინტი": "Tint",
    "ტონი": "Tone",
    "ექსპოზიცია": "Exposure",
    "კონტრასტი": "Contrast",
    "ნათელები": "Highlights",
    "ჩრდილები": "Shadows",
    "თეთრები": "Whites",
    "შავები": "Blacks",
    "დეტალი და ფერი": "Detail & Color",
    "სიცხადე": "Clarity",
    "სიხასხასე": "Vibrance",
    "ფერი": "Color",
    "ტექსტურა": "Texture",
    "სიმკვეთრე": "Sharpen",
    "შავ-თეთრი": "Black & White",
    "სეპია": "Sepia",
    "ვინიეტი": "Vignette",
    "მალე": "Soon",
    "პანელის გახსნა / დაკეცვა": "Open / collapse the panel",
    "შეკეთება": "Heal",
    "შენახვა": "Save",
    "სლაიდერის განულება": "Reset this slider",
    "გასუფთავება": "Clear all",
    "ყველა სლაიდერის განულება": "Reset all sliders",

    # --- Filters manager (filters.py) -------------------------------------
    "შენ შეგიძლია მიმდინარე ედიტი ფილტრად შეინახო, ან მზა ფილტრები ფაილიდან ჩამოამატო.":
        "Save the current edit as a filter, or add ready-made filters from a file.",
    "შენახული ფილტრები: {n}": "Saved filters: {n}",
    "ფილტრის შექმნა": "Create filter",
    "მიმდინარე სლაიდერების მნიშვნელობებს ფილტრად შეინახავს":
        "Saves the current slider values as a filter",
    "რედაქტირება": "Edit",
    "შენახული ფილტრების გადარქმევა / განახლება / წაშლა":
        "Rename / refresh / delete saved filters",
    "იმპორტი": "Import",
    "ფილტრების ჩამოტვირთვა .json ფაილიდან": "Load filters from a .json file",
    "ექსპორტი": "Export",
    "ფილტრების შენახვა .json ფაილში გასაზიარებლად":
        "Save filters to a .json file to share",
    "ჩემი ფილტრი": "My filter",
    "ახალი ფილტრი": "New filter",
    "ფილტრის სახელი": "Filter name",
    "ფილტრი შენახულია: {name}": "Filter saved: {name}",
    "ჯერ ფილტრი არ შენახულა": "No filters saved yet",
    "ფილტრების რედაქტირება": "Edit filters",
    "ფილტრები აღარ არის": "No filters left",
    "სახელის გადარქმევა": "Rename",
    "მიმდინარე ედიტით განახლება": "Refresh from current edit",
    "წაშლა": "Delete",
    "გადარქმევა": "Rename",
    "ფილტრი განახლდა: {name}": "Filter refreshed: {name}",
    "ფილტრების იმპორტი": "Import filters",
    "ფილტრის ფაილი": "Filter file",
    "ყველა ფაილი": "All files",
    "დაიმატა {n} ფილტრი": "Added {n} filter(s)",
    "ფაილში ფილტრები ვერ მოიძებნა": "No filters found in the file",
    "ფილტრების ექსპორტი": "Export filters",
    "ყველას ერთ ფაილში": "All in one file",
    "ფილტრების შენახვა": "Save filters",
    "ექსპორტი დასრულდა: {n} ფილტრი": "Exported {n} filter(s)",
    "ფაილის ჩაწერა ვერ მოხერხდა": "Could not write the file",
    "დახურვა": "Close",

    # --- Crop tool (crop.py) ----------------------------------------------
    "თავისუფ.": "Free",
    "ორიგინ.": "Original",
    "საკუთარი": "Custom",
    "IG პორტრ. 4:5": "IG Portrait 4:5",
    "ჩავათრიე კუთხეები; აირჩიე ფორმა ან სოც. ქსელი":
        "Drag the corners; pick a shape or social network",
    "ფორმა": "Shape",
    "სოციალური ქსელები": "Social networks",
    "⇄ გადატრიალება (3:4 ⇄ 4:3)": "⇄ Flip (3:4 ⇄ 4:3)",
    "მონიშვნის 90°-ით გადატრიალება": "Rotate the selection by 90°",
    "მოჭრა": "Crop",
    "გაუქმება": "Cancel",
    "მონიშვნის სრულ სურათზე დაბრუნება": "Reset the selection to the whole image",
    "საკ.": "Cust.",
    "საკუთარი ზომა": "Custom size",
    "საკუთარი პროპორცია": "Custom ratio",
    "სიგანე : სიმაღლე  (მაგ. 4:5 ან 1200:800)":
        "Width : Height  (e.g. 4:5 or 1200:800)",
    "შეიყვანე ორი დადებითი რიცხვი": "Enter two positive numbers",
    "რიცხვები დადებითი უნდა იყოს": "Numbers must be positive",
    "არჩევა": "Select",
    "მოსაჭრელი არე ძალიან პატარაა": "The crop area is too small",
    "მთელი სურათია მონიშნული — არაფერი იცვლება":
        "The whole image is selected — nothing changes",
    "მოიჭრა → {w}×{h}px  ·  შენახვა ფაილში ჩასაწერად":
        "Cropped → {w}×{h}px  ·  Save to write it to a file",

    # --- Retouch / heal tool (heal.py) ------------------------------------
    "ავტო შეკეთება": "Auto heal",
    "კლონი": "Clone",
    "თანხვედრილი": "Aligned",
    "სარკისებური": "Mirror",
    "ფუნჯის ზომა": "Brush size",
    "სიძლიერე": "Strength",
    "კიდის სიფაფუკე": "Edge softness",
    "Ctrl+Z — ბოლო მოქმედების გაუქმება": "Ctrl+Z — undo the last action",
    "Alt+დააწკაპე — წყაროს არჩევა; მერე ხატე ზუსტი ასლი. "
    "ბორბალი ან [ ] ფუნჯის ზომას ცვლის.":
        "Alt+click — pick a source; then paint an exact copy. "
        "The wheel or [ ] changes the brush size.",
    "დააწკაპე ან გადაუსვი ლაქას — ვშლი მახლობელი სუფთა ფონის "
    "ასლით. ბორბალი ან [ ] ფუნჯის ზომას ცვლის.":
        "Click or drag over a blemish — I erase it with a copy of nearby "
        "clean background. The wheel or [ ] changes the brush size.",
    "წყარო არჩეულია — ახლა ხატე ასლი": "Source picked — now paint the copy",
    "ჯერ Alt+დააწკაპე წყაროზე": "First Alt+click a source",
    "გაუქმება შეუძლებელია — სხვა სურათია":
        "Can't undo — a different image is open",

    # --- Navigation / cull / undo dialogs (nav.py) ------------------------
    "შენახვა?": "Save?",
    "სურათი შეცვლილია": "The image has changed",
    "{fname} — შევინახო კოპია _edited-ში?":
        "{fname} — save a copy to _edited?",
    "არ შევინახო": "Don't save",
    "ჯერ მიუთითე დახარისხების ფოლდერები  ·  ⚙ პარამეტრები":
        "Set the sorting folders first  ·  ⚙ Settings",
    "შენახულია → {name}  ·  Ctrl+Z": "Kept → {name}  ·  Ctrl+Z",
    "გადაგდებულია → {name}  ·  Ctrl+Z": "Rejected → {name}  ·  Ctrl+Z",
    "მიუთითე სად გადავიდეს დატოვებული და გადაგდებული "
    "ფოტოები. სანამ ორივე არ მითითებულა, ღილაკები არ მუშაობს.":
        "Set where kept and rejected photos go. Until both are set, the "
        "buttons don't work.",
    "✓ შენახვა (keeper) — დატოვებული ფოტოები":
        "✓ Keep (keeper) — photos you keep",
    "✗ გადაგდება (reject) — გადაგდებული ფოტოები":
        "✗ Reject — photos you discard",
    "დახარისხების ფოლდერები შენახულია": "Sorting folders saved",
    "ფოლდერები არასრულია — გადარჩევა ჯერ არ მუშაობს":
        "Folders incomplete — culling doesn't work yet",
    "ფოტოების გადარჩევა (culling)": "Culling photos",
    "ათვალიერებ ფოტოებს და თითოეულს ანაწილებ ორ "
    "ფოლდერში — დასატოვებელი და გადასაგდები.":
        "You browse the photos and sort each into two folders — keep and "
        "discard.",
    "მიმდინარე ფოტოს გადააქვს დასატოვებელ ფოლდერში.":
        "Moves the current photo to the keep folder.",
    "მიმდინარე ფოტოს გადააქვს გადასაგდებ ფოლდერში.":
        "Moves the current photo to the discard folder.",
    "პარამეტრები": "Settings",
    "მიუთითე ეს ორი ფოლდერი — სანამ არ მიუთითებ, ღილაკები არ მუშაობს.":
        "Set these two folders — until you do, the buttons don't work.",
    "Ctrl+Z აბრუნებს ნებისმიერ გადატანას.": "Ctrl+Z undoes any move.",
    "გასაგებია": "Got it",
    "გასაუქმებელი არაფერია": "Nothing to undo",
    "გასამეორებელი არაფერია": "Nothing to redo",
    "შეცდომა: {e}": "Error: {e}",
    "დაბრუნდა: {name}": "Restored: {name}",
    "გადატანილია: {name}": "Moved: {name}",
    "რედაქტირების გაუქმება შეუძლებელია — სხვა ფოლდერია":
        "Can't undo the edit — a different folder is open",
    "რედაქტირების გაუქმება შეუძლებელია — ფაილი აღარ არსებობს":
        "Can't undo the edit — the file no longer exists",

    # --- Save-as dialog (saving.py) ---------------------------------------
    "შენახვა როგორც": "Save as",
    "ჯერ გახსენი სურათი": "Open an image first",
    "საქაღალდე": "Folder",
    "აირჩიე საქაღალდე": "Choose a folder",
    "სახელი": "Name",
    "ხარისხი": "Quality",
    "გამოვიყენე ეს კონფიგი სწრაფი შენახვისთვის":
        "Use this config for quick save",
    "ფორმატი": "Format",
    "შენახულია → {name}": "Saved → {name}",
}

# Register every pack so t() can find it. (Georgian = default, no pack needed.)
i18n.register("en", CATALOG_EN)
