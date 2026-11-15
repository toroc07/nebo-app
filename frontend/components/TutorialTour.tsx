"use client";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ArrowLeft, ArrowRight, X } from "lucide-react";
import s from "./tutorial.module.css";

/** A numbered point on a screenshot: x/y is the control, lx/ly its label (both in % of the image). */
type Callout = { x: number; y: number; lx: number; ly: number; label: string; text: string };
type Step = { title: string; text: string; image: string; alt: string; demo?: boolean; callouts: Callout[] };

/*
 * Screenshots live in public/tutorial (1440×900, taken from the running app). If the UI moves,
 * retake them and update the x/y of the callouts below.
 */
const STEPS: Step[] = [
  {
    title: "Start screen",
    text: "Everything begins on the landing pad. From here you launch into the sky or reopen this guide.",
    image: "/tutorial/home.webp",
    alt: "Nebo start screen with the Start and Tutorial buttons on the wall screen.",
    callouts: [
      { x: 59.7, y: 47.2, lx: 52, ly: 72, label: "Start", text: "Lifts off and takes you to the cockpit. The controls unlock when the flight ends." },
      { x: 81, y: 47.2, lx: 82, ly: 72, label: "Tutorial", text: "Opens this guide again whenever you need it." },
    ],
  },
  {
    title: "Cockpit",
    text: "You fly over the SPHEREx all-sky map. The console at the bottom tells you where you are and what to do next.",
    image: "/tutorial/cockpit.webp",
    alt: "Cockpit view of the infrared all-sky map with the navigation console at the bottom.",
    callouts: [
      { x: 50, y: 50, lx: 30, ly: 24, label: "Sky map", text: "Drag to move around the sky. It is the SPHEREx all-sky map from NASA/IPAC IRSA." },
      { x: 24.8, y: 91, lx: 12, ly: 60, label: "Console tabs", text: "Sky map, Objects, Catalogs and Tools. Objects lists the featured targets." },
      { x: 44.2, y: 90, lx: 40, ly: 66, label: "Map centre", text: "Where you are pointing, in RA/Dec. Click the sky map to fly to a spot." },
      { x: 82.5, y: 89.8, lx: 68, ly: 50, label: "Zoom", text: "Zoom in and out, or jump back to All sky. The gauge shows the field of view." },
      { x: 93.2, y: 90.2, lx: 89, ly: 36, label: "View images", text: "Fetches the SPHEREx images of the field at the centre, one per epoch. A new field can take a minute." },
    ],
  },
  {
    title: "Around the cockpit",
    text: "Talk with other explorers, see where on Earth this sky is overhead, and open whatever sits under the centre mark.",
    image: "/tutorial/cockpit-tools.webp",
    alt: "Cockpit with the public chat open on the left, the Earth globe and the nearest catalogued object on the console.",
    callouts: [
      { x: 4.5, y: 4.2, lx: 34, ly: 8, label: "Chat", text: "Public chat: one room per featured object, or a general room. Messages are filtered and deleted after 24 hours." },
      { x: 13.6, y: 35.8, lx: 38, ly: 32, label: "Chat room", text: "Your nickname is made up for you. No links or personal data: they are blocked." },
      { x: 50, y: 50, lx: 64, ly: 30, label: "Centre mark", text: "View images opens the object under this mark, even if you did not select it." },
      { x: 7.7, y: 90.7, lx: 18, ly: 70, label: "Earth globe", text: "The place on Earth where the map centre is straight overhead right now. It follows the map." },
      { x: 81.4, y: 95.5, lx: 70, ly: 72, label: "Nearest object", text: "The closest featured object to the map centre. Click it to fly there." },
      { x: 95.6, y: 4.2, lx: 86, ly: 16, label: "Back", text: "Returns to the start screen." },
    ],
  },
  {
    title: "Choose a target",
    text: "Pick a featured object, or type any position on the sky.",
    image: "/tutorial/coords.webp",
    alt: "Coordinates panel open over the sky map, with the list of featured objects in the console.",
    callouts: [
      { x: 16.4, y: 94, lx: 9, ly: 62, label: "Objects", text: "Featured targets with their distance from the map centre. Click one to fly there." },
      { x: 67.4, y: 89, lx: 82, ly: 74, label: "Coords", text: "Opens the coordinates panel to type a position." },
      { x: 60, y: 52, lx: 84, ly: 28, label: "RA / Dec", text: "Right ascension and declination. Use the arrows, or switch the format to decimal degrees." },
      { x: 65.8, y: 70.8, lx: 84, ly: 52, label: "Apply", text: "Flies the ship to that position. Reset clears the form." },
    ],
  },
  {
    title: "Compare epochs",
    text: "View images opens the field: one image of the same patch of sky per SPHEREx epoch.",
    image: "/tutorial/field.webp",
    alt: "Field screen with an infrared image, the epoch timeline and the blink controls.",
    demo: true,
    callouts: [
      { x: 47, y: 45, lx: 18, ly: 22, label: "Field image", text: "North up, east left. One pixel is 6.15″. The box marks where the target should be." },
      { x: 39, y: 78.2, lx: 14, ly: 92, label: "Blink", text: "Compare epochs plays them in a loop, so anything that moved jumps out." },
      { x: 57.5, y: 78.8, lx: 50, ly: 93, label: "Speed", text: "How long each epoch stays on screen." },
      { x: 79, y: 79.5, lx: 76, ly: 93, label: "Epochs", text: "Step through the dates one by one, or use the ← → keys." },
      { x: 84.4, y: 25.6, lx: 88, ly: 9, label: "Detector", text: "Each detector is a different band. Compare within one; WISE 0855 only shows in D6." },
    ],
  },
  {
    title: "Layers, links and analysis",
    text: "Check the field against other catalogues, share exactly what you see, and open the analysis panel.",
    image: "/tutorial/field-tools.webp",
    alt: "Field screen with the Gaia layer on, the Copy link button, the layer buttons and the 3D model on the wall tablet.",
    callouts: [
      { x: 64.3, y: 17.3, lx: 66, ly: 5, label: "Copy link", text: "The address bar always holds this exact view (object or coordinates, detector, size, epoch). Copy it to share." },
      { x: 80.9, y: 36.1, lx: 92, ly: 22, label: "Layers", text: "Gaia DR3 stars, CatWISE infrared sources and detected changes, each with its own switch." },
      { x: 44, y: 52, lx: 28, ly: 40, label: "Catalogue rings", text: "Gaia stars moved to the date of each epoch. Click one for its distance and motion." },
      { x: 38.2, y: 27.7, lx: 22, ly: 12, label: "Analysis", text: "Spectrum, RGB and models. Parts built from demonstration profiles say \"simulated\"." },
      { x: 55.5, y: 31.3, lx: 46, ly: 5, label: "Alignment", text: "Checks that the epochs line up with Gaia before you trust a change." },
      { x: 18.5, y: 71.7, lx: 12, ly: 92, label: "3D model", text: "An illustration of the object, from its type and temperature. Not SPHEREx data." },
    ],
  },
  {
    title: "Read the result",
    text: "Nebo shows what changed, not what it means. Read every change as a candidate, never a discovery.",
    image: "/tutorial/field.webp",
    alt: "Field screen highlighting the observation date, the data release and the observed-change note.",
    demo: true,
    callouts: [
      { x: 66, y: 69, lx: 64, ly: 93, label: "Observed change", text: "A change between images is a candidate signal, never a confirmed discovery." },
      { x: 31.5, y: 70.4, lx: 16, ly: 92, label: "Observation date", text: "The date of the epoch on screen, from the API. An epoch can span days or weeks." },
      { x: 85, y: 62.4, lx: 88, ly: 96, label: "Data release", text: "The release each image comes from (DR1, QR3…), straight from the API." },
      { x: 80.8, y: 49.3, lx: 89, ly: 12, label: "Catalogued object", text: "Known objects are listed apart from changes nobody has explained yet." },
      { x: 55.6, y: 27.7, lx: 40, ly: 8, label: "Difference", text: "Subtracts the epochs so only what changed stays bright." },
    ],
  },
];

export default function TutorialTour({ onClose, onStart }: { onClose: () => void; onStart: () => void }) {
  const [step, setStep] = useState(0);
  const [active, setActive] = useState<number | null>(null);
  const title = useRef<HTMLHeadingElement>(null);
  // Keyboard and screen-reader users land on each new step title.
  useEffect(() => title.current?.focus(), [step]);
  const last = step === STEPS.length - 1;
  const go = (n: number) => {
    setActive(null);
    setStep(n);
  };
  const next = () => (last ? onStart() : go(step + 1));
  const previous = () => (step === 0 ? onClose() : go(step - 1));
  function onKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowRight") next();
    else if (event.key === "ArrowLeft") previous();
    else if (event.key === "Escape") onClose();
    else return;
    event.preventDefault();
  }
  const current = STEPS[step];
  return (
    <div className={s.backdrop} role="dialog" aria-modal="true" aria-labelledby="tour-title" onKeyDown={onKey}>
      <div className={s.panel}>
        <header className={s.head}>
          <p className={s.status}>
            <span aria-hidden="true" /> Tutorial · step {String(step + 1).padStart(2, "0")} /{" "}
            {String(STEPS.length).padStart(2, "0")}
          </p>
          <button type="button" className={s.close} onClick={onClose} aria-label="Close the tutorial">
            <X aria-hidden="true" />
          </button>
          <ol className={s.progress} aria-hidden="true">
            {STEPS.map((item, i) => (
              <li key={item.title} data-on={i <= step || undefined} />
            ))}
          </ol>
          <h2 id="tour-title" ref={title} tabIndex={-1}>
            {current.title}
          </h2>
          <p className={s.lead}>{current.text}</p>
        </header>

        <div key={step} className={s.stage}>
          <figure className={s.shot}>
            <img src={current.image} alt={current.alt} width={1440} height={900} draggable={false} />
            {/* Leader lines: % coordinates, the stroke keeps its width when the image scales. */}
            <svg className={s.lines} viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              {current.callouts.map((c, i) => (
                <line
                  key={c.label}
                  x1={c.x}
                  y1={c.y}
                  x2={c.lx}
                  y2={c.ly}
                  vectorEffect="non-scaling-stroke"
                  data-on={active === i || undefined}
                  style={{ animationDelay: `${i * 120}ms` }}
                />
              ))}
            </svg>
            {current.callouts.map((c, i) => (
              <span key={c.label} aria-hidden="true">
                <span
                  className={s.point}
                  style={{ left: `${c.x}%`, top: `${c.y}%` }}
                  data-on={active === i || undefined}
                  onPointerEnter={() => setActive(i)}
                  onClick={() => setActive(i)}
                >
                  {i + 1}
                </span>
                <span
                  className={s.tag}
                  style={{ left: `${c.lx}%`, top: `${c.ly}%`, animationDelay: `${i * 120 + 200}ms` }}
                  data-on={active === i || undefined}
                  onPointerEnter={() => setActive(i)}
                  onClick={() => setActive(i)}
                >
                  {c.label}
                </span>
              </span>
            ))}
            {current.demo && <figcaption>Screenshot made with synthetic demo data.</figcaption>}
          </figure>

          <ol className={s.list}>
            {current.callouts.map((c, i) => (
              <li key={c.label}>
                <button
                  type="button"
                  aria-pressed={active === i}
                  data-on={active === i || undefined}
                  onClick={() => setActive(active === i ? null : i)}
                  onPointerEnter={() => setActive(i)}
                  onFocus={() => setActive(i)}
                >
                  <span className={s.num} aria-hidden="true">
                    {i + 1}
                  </span>
                  <span>
                    <strong>{c.label}</strong>
                    <small>{c.text}</small>
                  </span>
                </button>
              </li>
            ))}
          </ol>
          {/* Small screens: the chips hide their text, so the selected one is read out here. */}
          <p className={s.detail} aria-hidden="true">
            {active === null ? "Tap a number to see what it does." : current.callouts[active].text}
          </p>
        </div>

        <nav className={s.nav} aria-label="Tutorial steps">
          <button type="button" className={s.back} onClick={previous}>
            <ArrowLeft aria-hidden="true" /> {step === 0 ? "Menu" : "Back"}
          </button>
          <button type="button" className={s.next} onClick={next}>
            {last ? "Launch" : "Next"} <ArrowRight aria-hidden="true" />
          </button>
          <button type="button" className={s.skip} onClick={onStart}>
            Skip tutorial
          </button>
        </nav>
      </div>
    </div>
  );
}
