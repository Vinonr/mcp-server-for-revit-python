# Recording guide: capturing your voice, face and body

Your recordings set the quality ceiling: no model fixes a bad recording.
Record everything in one session so your voice, look and lighting match.

## 1. Voice samples (for the voice clone)

| Item | Spec |
|---|---|
| Room | Small, furnished, quiet. **Switch off the AC, fans and ceiling fan**: their hum gets cloned. Avoid bare tiled rooms because of the echo. |
| Mic | USB condenser or lavalier, 15–20 cm from your mouth, with a pop filter. A phone voice memo in a quiet room works, but the clone will sound worse. |
| Format | WAV, 48 kHz/24-bit or 44.1 kHz/16-bit, mono. No music, EQ, compression or noise removal. |
| Level | Peaks around −6 dBFS. Never clip (`check` warns above −0.5 dBFS). |
| Amount | 3–5 takes of 30–90 s each, **2–3 minutes in total**. Instant cloning stops improving beyond about 3 minutes. Professional Voice Cloning needs 30+ minutes. |
| Delivery | Use the one register you want the avatar to have, such as client-presentation pace. Don't mix whispering, shouting and casual speech. |

Record these takes:

1. **Take 1–2:** read the passage below at presentation pace.
2. **Take 3:** speak for 60–90 s without a script, for example explaining a recent precast project to a client. Natural rhythm improves the clone's prosody.
3. **Take 4 (optional):** speak 60 s in Tamil, Malayalam or Hindi, whichever language you want the avatar to use. Do this even though the clone works across languages, because a native sample keeps your accent authentic.

> Good morning. I'm presenting our digital delivery approach for the precast
> package. We model every element to LOD 400, so each hollow-core slab, beam
> and column carries its reinforcement, embeds and lifting inserts. From Tekla
> Structures and Revit, the model data flows into Autodesk Construction Cloud
> for coordination, and into SAP S/4HANA, where production orders, yard
> inventory and dispatch are tracked against the same element IDs. At handover,
> the client receives COBie and IFC deliverables mapped to their asset
> information requirements. Four things matter here: accuracy, traceability,
> schedule certainty, and cost control. Questions? Let's walk through the
> 4D sequence and the 5D cost report together.

Save the takes to `data/voice_samples/` as `take1.wav`, `take2.wav` and so on.

## 2. Face and body footage

### HeyGen Digital Twin (hosted backend, `character_type = "avatar"`)

Record in the HeyGen web app by following its instructions, including the
**consent video**. That video is how HeyGen verifies that the avatar is you.
Use the camera specs below. Copy the resulting avatar ID into `character_id`.

### Base footage (local backend)

Record 30–60 s of continuous footage to `data/base_footage.mp4`. The tool
loops it forward and backward to match each script's length, then the
lip-sync model re-drives your mouth.

| Item | Spec |
|---|---|
| Camera | 1080p minimum, 4K better. 25 or 30 fps. **Lock focus, exposure and white balance.** Use a tripod with the lens at eye level. |
| Framing | **Waist-up** if you want body presence (gestures, posture). Chest-up if you want a closer talking head. Frame it the way you want the final video to look. |
| Light | A soft key light at 45°, a fill light on the other side, and nothing bright behind you (no window). Don't mix daylight with warm bulbs. |
| Wardrobe | Solid colours. No fine stripes or checks, which shimmer on video. **No employer logos or ID lanyards** on a personal-consultancy avatar unless the employer has approved it. |
| Background | Plain, or your actual office. Keep it static: no moving people or screens. |
| Performance | Look into the lens and talk naturally. Keep gestures moderate and below the chest. **Never cross your face with your hands.** Every few sentences, **pause for 1–2 s with your mouth closed**, because lip-sync models anchor on these frames. Keep head turns under about 30°. |

## 3. Photo (optional, for a HeyGen Photo Avatar, `character_type = "talking_photo"`)

Use a front-facing, eye-level, sharp photo at 1080 px or more, in even light.
Keep a neutral expression with your mouth closed. No sunglasses, and no hands
near your face. A photo avatar animates your head only; the Digital Twin
gives you the body.

## 4. Before you upload

```bash
python -m avatar_studio --config avatar.toml check
```

Fix every `ERROR`. Most `WARN` items are worth re-recording too; it takes a
few minutes and lifts the quality of every video you make afterwards.
