# Universal `ADBE` MatchNames Reference (Locale-Safe for EN / RU AE 2020)

Always prefer `matchName` strings over UI display names (`"Fill"`, `"Заливка"`, `"Slider Control"`) so `.jsx` scripts run identically on English, Russian, and other localized installations of After Effects 2020.

## 1. Core Layer Groups & Transform Properties

| UI Name (EN) | MatchName |
| :--- | :--- |
| Transform Group | `ADBE Transform Group` |
| Anchor Point | `ADBE Anchor Point` |
| Position | `ADBE Position` |
| X / Y / Z Position (Separated) | `ADBE Position_0`, `ADBE Position_1`, `ADBE Position_2` |
| Scale | `ADBE Scale` |
| Rotation (2D) / Z Rotation (3D) | `ADBE Rotate Z` |
| X / Y Rotation (3D) | `ADBE Rotate X`, `ADBE Rotate Y` |
| Opacity | `ADBE Opacity` |
| Effects Group | `ADBE Effect Parade` |
| Masks Group | `ADBE Mask Parade` |
| Markers | `ADBE Marker` |
| Text Document (`Source Text`) | `ADBE Text Properties` -> `ADBE Text Document` |

## 2. Vector / Shape Layer MatchNames

| Shape Element | MatchName |
| :--- | :--- |
| Root Contents | `ADBE Root Vectors Group` |
| Vector Group | `ADBE Vector Group` |
| Group Contents | `ADBE Vectors Group` |
| Group Transform | `ADBE Vector Transform Group` |
| Rectangle Path | `ADBE Vector Shape - Rect` (`ADBE Vector Rect Size`, `ADBE Vector Rect Position`, `ADBE Vector Rect Roundness`) |
| Ellipse Path | `ADBE Vector Shape - Ellipse` (`ADBE Vector Ellipse Size`) |
| Parametric Polystar | `ADBE Vector Shape - Star` |
| Bezier Path | `ADBE Vector Shape - Group` (`ADBE Vector Shape`) |
| Fill | `ADBE Vector Graphic - Fill` (`ADBE Vector Fill Color`, `ADBE Vector Fill Opacity`) |
| Stroke | `ADBE Vector Graphic - Stroke` (`ADBE Vector Stroke Color`, `ADBE Vector Stroke Width`, `ADBE Vector Stroke Opacity`) |
| Trim Paths | `ADBE Vector Filter - Trim` (`ADBE Vector Trim Start`, `ADBE Vector Trim End`, `ADBE Vector Trim Offset`) |
| Repeater | `ADBE Vector Filter - Repeater` (`ADBE Vector Repeater Copies`) |
| Round Corners | `ADBE Vector Filter - RC` (`ADBE Vector RoundCorner Radius`) |

## 3. Common Built-in Effects (`lyr.property("ADBE Effect Parade").addProperty(...)`)

| Effect (EN / RU) | MatchName | Key Child Properties |
| :--- | :--- | :--- |
| Fill / Заливка | `ADBE Fill` | `ADBE Fill-0002` (Color), `ADBE Fill-0005` (Opacity) |
| Glow / Свечение | `ADBE Glo2` | `ADBE Glo2-0002` (Threshold), `ADBE Glo2-0003` (Radius), `ADBE Glo2-0004` (Intensity) |
| Drop Shadow / Тень | `ADBE Drop Shadow` | `ADBE Drop Shadow-0001` (Color), `ADBE Drop Shadow-0002` (Opacity), `ADBE Drop Shadow-0003` (Direction), `ADBE Drop Shadow-0004` (Distance), `ADBE Drop Shadow-0005` (Softness) |
| Gaussian Blur / Размытие по Гауссу | `ADBE Gaussian Blur 2` | `ADBE Gaussian Blur 2-0001` (Blurriness), `ADBE Gaussian Blur 2-0002` (Dimensions) |
| Fast Box Blur | `ADBE Box Blur2` | `ADBE Box Blur2-0001` (Blur Radius), `ADBE Box Blur2-0002` (Iterations) |
| Gradient Ramp / Градиент | `ADBE Ramp` | `ADBE Ramp-0001` (Start Point), `ADBE Ramp-0002` (Start Color), `ADBE Ramp-0003` (End Point), `ADBE Ramp-0004` (End Color) |
| Tint / Оттенок | `ADBE Tint` | `ADBE Tint-0001` (Map Black To), `ADBE Tint-0002` (Map White To), `ADBE Tint-0003` (Amount) |
| Curves / Кривые | `ADBE CurvesCustom` | — |
|Turbulent Displace | `ADBE Turbulent Displace` | `ADBE Turbulent Displace-0002` (Amount), `ADBE Turbulent Displace-0003` (Size) |
| Linear Wipe | `ADBE Linear Wipe` | `ADBE Linear Wipe-0001` (Transition Completion), `ADBE Linear Wipe-0002` (Wipe Angle), `ADBE Linear Wipe-0003` (Feather) |

## 4. Expression Controls (`Effects -> Expression Controls`)

| Control | MatchName | Value Property |
| :--- | :--- | :--- |
| Slider Control | `ADBE Slider Control` | `ADBE Slider Control-0001` |
| Color Control | `ADBE Color Control` | `ADBE Color Control-0001` |
| Checkbox Control | `ADBE Checkbox Control` | `ADBE Checkbox Control-0001` |
| Point Control | `ADBE Point Control` | `ADBE Point Control-0001` |
| Angle Control | `ADBE Angle Control` | `ADBE Angle Control-0001` |
| Layer Control | `ADBE Layer Control` | `ADBE Layer Control-0001` |
