// Reference objects drawn on the cockpit sky map so visitors can find their way around: famous
// sights that stand out in the infrared map, and the nearest stars and brown dwarfs (the kind of
// cold, nearby object the "Planet X" search is about). They are only labels: not Nebo targets,
// not detections, and clicking one does nothing.
//
// Positions: SIMBAD (ICRS, epoch J2000), resolved 2026-11-16 through the SIMBAD mirror at
// simbad.harvard.edu. The fastest nearby stars have moved up to ~1′ since 2000 (Barnard's Star,
// a Nebo target, is propagated by the backend instead); at map scale that is invisible.

export type LandmarkKind =
  | "Nebula"
  | "Galaxy"
  | "Star cluster"
  | "Galactic Centre"
  | "Bright star"
  | "Nearby star"
  | "Brown dwarf";

export type Landmark = { name: string; kind: LandmarkKind; ra: number; dec: number };

export const LANDMARKS: readonly Landmark[] = [
  // Nebulae and star-forming regions
  { name: "Orion Nebula (M42)", kind: "Nebula", ra: 83.8201, dec: -5.3876 },
  { name: "Horsehead Nebula", kind: "Nebula", ra: 85.24583, dec: -2.45833 },
  { name: "Crab Nebula (M1)", kind: "Nebula", ra: 83.6324, dec: 22.0174 },
  { name: "Lagoon Nebula (M8)", kind: "Nebula", ra: 270.90417, dec: -24.38667 },
  { name: "Carina Nebula", kind: "Nebula", ra: 161.25929, dec: -59.69994 },
  { name: "Rho Ophiuchi cloud", kind: "Nebula", ra: 247.025, dec: -24.54167 },
  // Galaxies and the centre of ours
  { name: "Andromeda Galaxy (M31)", kind: "Galaxy", ra: 10.68471, dec: 41.26875 },
  { name: "Triangulum Galaxy (M33)", kind: "Galaxy", ra: 23.46207, dec: 30.66018 },
  { name: "Large Magellanic Cloud", kind: "Galaxy", ra: 80.89417, dec: -69.75611 },
  { name: "Small Magellanic Cloud", kind: "Galaxy", ra: 13.15833, dec: -72.80028 },
  { name: "Galactic Centre (Sgr A*)", kind: "Galactic Centre", ra: 266.41682, dec: -29.00782 },
  // Star clusters
  { name: "Pleiades (M45)", kind: "Star cluster", ra: 56.60083, dec: 24.11389 },
  { name: "Eagle Nebula cluster (M16)", kind: "Star cluster", ra: 274.688, dec: -13.792 },
  { name: "Hercules Cluster (M13)", kind: "Star cluster", ra: 250.42347, dec: 36.46132 },
  // Bright stars
  { name: "Sirius", kind: "Bright star", ra: 101.28716, dec: -16.71612 },
  { name: "Betelgeuse", kind: "Bright star", ra: 88.79294, dec: 7.40706 },
  { name: "Rigel", kind: "Bright star", ra: 78.63447, dec: -8.20164 },
  { name: "Aldebaran", kind: "Bright star", ra: 68.98016, dec: 16.5093 },
  { name: "Antares", kind: "Bright star", ra: 247.35192, dec: -26.432 },
  { name: "Arcturus", kind: "Bright star", ra: 213.9153, dec: 19.18241 },
  { name: "Vega", kind: "Bright star", ra: 279.23473, dec: 38.78369 },
  { name: "Deneb", kind: "Bright star", ra: 310.35798, dec: 45.28034 },
  { name: "Polaris", kind: "Bright star", ra: 37.95456, dec: 89.26411 },
  // The Sun's neighbours
  { name: "Proxima Centauri", kind: "Nearby star", ra: 217.42894, dec: -62.67949 },
  { name: "Alpha Centauri A", kind: "Nearby star", ra: 219.90206, dec: -60.83399 },
  { name: "Wolf 359", kind: "Nearby star", ra: 164.1205, dec: 7.01472 },
  { name: "Lalande 21185", kind: "Nearby star", ra: 165.83415, dec: 35.96988 },
  { name: "Epsilon Eridani", kind: "Nearby star", ra: 53.23269, dec: -9.45826 },
  { name: "Tau Ceti", kind: "Nearby star", ra: 26.01701, dec: -15.93748 },
  { name: "Ross 128", kind: "Nearby star", ra: 176.93499, dec: 0.80456 },
  { name: "Teegarden's Star", kind: "Nearby star", ra: 43.25372, dec: 16.88129 },
  { name: "61 Cygni A", kind: "Nearby star", ra: 316.72475, dec: 38.74942 },
  // Brown dwarfs
  { name: "Luhman 16", kind: "Brown dwarf", ra: 162.32881, dec: -53.31947 },
  { name: "Gliese 229B", kind: "Brown dwarf", ra: 92.645, dec: -21.86667 },
];
