# After Effects 2020 ES3 ExtendScript Pitfalls & Recipes

Adobe After Effects 2020 uses the legacy **ExtendScript (ECMAScript 3)** engine (`AfterFX.exe` 17.x). Keep these pitfalls in mind whenever authoring `.jsx` scripts:

## 1. Forbidden ES5 / ES6 Syntax
- **Variables & Functions:** Always use `var` and `function (...) {}`. Never use `let`, `const`, arrow functions `=>`, default parameters `function f(x = 1)`, rest/spread `...args`, or destructuring.
- **Strings:** Never use backtick template literals `` `Hello ${name}` `` or `.startsWith()` / `.endsWith()` / `.includes()` / `.repeat()`. Use `+` concatenation and `str.indexOf("prefix") === 0`.
- **Arrays & Objects:** `Array.prototype.forEach`, `.map`, `.filter`, `.reduce`, `.some`, `.every`, `.find`, `Array.isArray`, `Object.keys`, `Object.values`, `Object.assign`, and `JSON.stringify` **do not exist**. Always write standard `for (var i = 0; i < arr.length; i++)` loops, and avoid trailing commas before `}` or `]`.
- **1-Based Indexing:** AE collections (`proj.item(i)`, `comp.layer(i)`, `group.property(i)`, `prop.keyTime(k)`) are **1-based** (`1 .. numItems` / `numLayers` / `numProperties` / `numKeys`), whereas JavaScript arrays (`[x, y]`) are **0-based**!

## 2. `setTemporalEaseAtKey` Array Dimension Trap
`prop.setTemporalEaseAtKey(keyIndex, inEaseArray, outEaseArray)` throws `"Bad argument: ease array length does not match..."` if the array length does not match the property's temporal dimension:
- **1D (`Opacity`, `Rotation`, `Slider`):** `[ease]` (length 1)
- **2D (`Scale` on 2D layer? Wait — `Scale` in AE is ALWAYS `ThreeD` `[sx, sy, 100]` or check `propertyValueType`!):**
  - `Position` (spatial `TwoD_SPATIAL` / `ThreeD_SPATIAL`): temporal ease takes **length 1** `[ease]`!
  - `Scale` (`ThreeD`): temporal ease takes **length 3** `[ease, ease, ease]` even on 2D layers!
  - `TwoD` non-spatial properties: length **2** `[ease, ease]`.
- **Best Practice:** Pass `include_stdlib=True` to `ae_write_script` and call `AEH.easyEase(prop, 75)`, which inspects `prop.propertyValueType` automatically!

## 3. Modifying `TextDocument`
Reading `lyr.property("Source Text").value` returns a **copy** of `TextDocument`. Mutating fields does nothing until you assign it back with `.setValue(doc)`:
```javascript
var src = txtLayer.property("ADBE Text Properties").property("ADBE Text Document");
var doc = src.value;
doc.text = "Новый заголовок";
doc.fontSize = 72;
doc.fillColor = [1, 1, 1];
doc.applyFill = true;
doc.justification = ParagraphJustification.CENTER_JUSTIFY;
src.setValue(doc);
```

## 4. Shape Layer Hierarchy (`ADBE Root Vectors Group`)
When building a rectangle or ellipse inside a `ShapeLayer`, add the Group first, then add Path + Fill/Stroke into that group's `"ADBE Vectors Group"`:
```javascript
var shapeLayer = comp.layers.addShape();
shapeLayer.name = "Card BG";
var rootVectors = shapeLayer.property("ADBE Root Vectors Group");
var grp = rootVectors.addProperty("ADBE Vector Group");
var contents = grp.property("ADBE Vectors Group");

var rect = contents.addProperty("ADBE Vector Shape - Rect");
rect.property("ADBE Vector Rect Size").setValue([600, 180]);
rect.property("ADBE Vector Rect Roundness").setValue(24);

var fill = contents.addProperty("ADBE Vector Graphic - Fill");
fill.property("ADBE Vector Fill Color").setValue([0.12, 0.14, 0.22]);
```
