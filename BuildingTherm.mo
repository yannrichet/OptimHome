

model BuildingTherm
  "Maison R+2 (3 x 40 m2) - modele annuel pour optimisation NSGA-II.

  ============================================================================
  METEO REELLE (TMY) — cf. section 2 du notebook
  ============================================================================
  Fichier weather.txt : table 8761 x 3 = [temps s ; T2m K ; G(h) W/m2],
  pas horaire, lue par CombiTimeTable (interpolation lineaire, extrapolation
  PERIODIQUE pour la mise en regime au-dela d'un an). Source PVGIS v5.2 (ou
  equivalent), pour le point geographique (lat/lon, altitude) choisi par
  l'utilisateur. dTout [K] est un decalage climatique uniforme (variabilite
  interannuelle + ilot de chaleur ; fixe a +1 K dans cette optimisation
  deterministe, cf. section 6 du notebook).
  Apports solaires interieurs : Qsol = fsol * 0.5 * Awin * G(h) — G(h) est
  horizontal, 0.5 projette sur des baies verticales multi-orientees avec
  masques proches, fsol porte le facteur solaire vitrage + occultations.

  ============================================================================
  GEOMETRIE : PARALLELEPIPEDE A BASE CARREE, EMPRISE ET HAUTEUR PARAMETRABLES
  ============================================================================
  Deux parametres pilotent toute la geometrie : Sfloor (emprise au sol, m2)
  et Htot (hauteur totale du batiment, m). V = Sfloor*Htot. L'emprise est un
  CARRE de surface Sfloor (cote = sqrt(Sfloor)), d'ou le perimetre de facade
  : Awall = 4*sqrt(Sfloor)*Htot - Awin. Cas de
  reference (defaut) : Sfloor = 40 m2, Htot = 7.5 m (R+2, 3 niveaux de
  2.5 m, soit 120 m2 habitables) -> V = 300 m3, Awall ~ 170 m2, vitrages
  Awin = 20 m2 ; toiture, plancher bas, vitrages (U=1.4) et ponts
  thermiques (~15 %) agreges dans UAother, mis a l'echelle de Sfloor
  (UAother_ref = 58 W/K pour Sfloor_ref = 40 m2). Mono-zone : niveaux
  supposes brasses (cage d'escalier).

  ============================================================================
  MUR TRICOUCHE : ISOLANT INTERIEUR / PARPAING / ISOLANT EXTERIEUR
  ============================================================================
  L'optimiseur dispose de DEUX epaisseurs independantes :
    e_iti : isolant cote interieur (lambda = lam_iso)
    e_ite : isolant cote exterieur (meme materiau)
  Reseau RC a 6 noeuds (2 par couche), de l'interieur vers l'exterieur :
    Tair -[Rsi+Riti/4]- T1 -[Riti/2]- T2 -[Riti/4+Rblk/4]- T3 -[Rblk/2]- T4
         -[Rblk/4+Rite/4]- T5 -[Rite/2]- T6 -[Rite/4+Rse]- Tout
  La masse du parpaing (noeuds T3,T4) est ainsi correctement placee ENTRE
  les deux isolants : le modele capture l'arbitrage inertie/isolation qui
  oppose ITE (masse accessible, favorable a l'ete) et ITI (masse isolee).
  Epaisseurs nulles admises (garde-fou 0.1 mm).

  ============================================================================
  PHOTOVOLTAIQUE : 3 kWc EN AUTOCONSOMMATION (ressource fixe, non optimisee)
  ============================================================================
  L'utilisateur dispose d'un actif fixe : Ppv_kWc = 3 kWc de panneaux, non
  redimensionnes par l'optimiseur (ce n'est pas une variable de conception).
  Production : Ppv(t) = Ppv_kWc*1000 * (G(h,t)/1000) * PR, ou G(h,t) est
  l'irradiance globale HORIZONTALE du meme fichier TMY (reutilisee telle
  quelle, cf. section meteo). PR = 0.90 est un ratio de performance GLOBAL
  qui regroupe en un seul coefficient : (a) le gain d'un panneau incline
  plein sud (~30-35°, typique en toiture) par rapport a l'irradiance
  horizontale utilisee ici par simplicite, et (b) les pertes systeme
  habituelles (onduleur, temperature, salissure, cablage). Calibrage : la
  production annuelle obtenue (kWh/kWc/an) vaut approximativement
  PR*irradiation_horizontale_annuelle_du_TMY (kWh/m2/an) ; a comparer aux
  estimations PVGIS pour un plein sud incline optimal au point geographique
  considere. C'est une approximation documentee, pas une simulation
  d'inclinaison/orientation detaillee.

  AUTOCONSOMMATION : le productible sert en PRIORITE la charge electrique
  TOTALE, chauffage compris. Pelec = Qheat (chauffage, hypothese resistif
  direct COP=1) + Qcool/seer (PAC de rafraichissement) + ventilateurs de
  surventilation nocturne. Meme les matins/journees ensoleillees de mi-saison
  ou d'hiver contribuent donc a reduire l'import reseau du chauffage.
  A chaque instant :
    Pgrid_cool(t)  = max(Pelec(t) - Ppv(t), 0)   -- import reseau residuel
    Pself_cool(t)  = min(Pelec(t),  Ppv(t))      -- autoconsommation directe
    Pexport(t)     = max(Ppv(t) - Pelec(t), 0)   -- surplus injecte au reseau
  Eheat reste par ailleurs la demande de chauffage BRUTE (thermique, avant
  PV) ; ce sont Egrid_total/Eself_cool qui portent la consommation
  electrique NETTE totale (chauffage + froid), apres autoconsommation PV.

  ============================================================================
  SYSTEMES DIMENSIONNES PAR L'OPTIMISEUR
  ============================================================================
  Pheat     : chauffage proportionnel plafonne, consigne 19 C. Sous-dimensionne,
              il laisse chuter Tair pendant les vagues de froid -> objectif
              Tmin_hiver (extrait de la colonne Tair du CSV, apres 14 j de
              mise en regime).
  Pcool     : PAC de rafraichissement, consigne 26 C, SEER = seer.
  ach_day   : AERATION NATURELLE diurne (ouverture de fenetres), gratuite,
              activee par rampes continues si Tair > ~26 C ET Tout < Tair.
  ach_night : SURVENTILATION NOCTURNE electrique (22h-7h, ventilateurs
              0.15 Wh/m3), memes rampes + activation si Tair > ~24 C.
  Les rampes continues (needCool, vfrac, vopen) remplacent des seuils
  tout-ou-rien qui provoquaient un broutement d'evenements (simulations
  x100 plus lentes) — correctif de la phase 2 de l'etude.
  "

  // ---- Variables de conception (fz / NSGA-II) ----
  parameter Real Pheat = 8000 "puissance de chauffage installee [W]";
  parameter Real Pcool = 2000 "puissance froid PAC [W]";
  parameter Real ach_day = 1.5 "aeration naturelle diurne max [1/h]";
  parameter Real ach_night = 2 "surventilation nocturne electrique [1/h]";
  parameter Real e_ite = 0.16 "isolant exterieur [m]";
  parameter Real e_iti = 0.0 "isolant interieur [m]";

  // ---- Parametres physiques (nominaux ; a tirer pour une version robuste) ----
  parameter Real lam_iso = 0.036 "conductivite isolant [W/m.K]";
  parameter Real ach = 0.6 "renouvellement d'air hygienique [1/h]";
  parameter Real Qint = 400 "apports internes moyens [W]";
  parameter Real dTout = 1.0 "decalage climatique sur le TMY [K]";
  parameter Real fsol = 0.5 "facteur solaire vitrage x occultations [-]";
  parameter Real seer = 3.5 "SEER de la PAC [-]";

  // ---- Geometrie : parallelepipede a base carree, emprise au sol (Sfloor)
  // et hauteur totale (Htot) parametrables. L'emprise est un CARRE de
  // surface Sfloor (cote = sqrt(Sfloor)), d'ou le perimetre de facade.
  parameter Real Sfloor = 40 "surface au sol (emprise) [m2]";
  parameter Real Htot = 7.5 "hauteur totale du batiment [m]";
  parameter Real Awin = 20 "surface vitree totale [m2]";
  parameter Real UAother_ref = 58 "UA toiture+plancher+vitrages+ponts thermiques, cas de reference [W/K]";
  parameter Real Sfloor_ref = 40 "surface au sol de reference pour UAother_ref [m2]";
  parameter Real V = Sfloor*Htot "volume chauffe [m3]";
  parameter Real perimetre = 4*sqrt(Sfloor) "perimetre du carre de surface Sfloor (emprise carree)";
  parameter Real Awall = max(perimetre*Htot - Awin, 1) "surface opaque de mur, support de l'isolation [m2]";
  parameter Real UAother = UAother_ref*Sfloor/Sfloor_ref "toiture+plancher+vitrages+ponts thermiques, mis a l'echelle [W/K]";
  parameter Real Cair = 1.2*1006*V*6 "air + mobilier + cloisons [J/K]";

  // ---- Mur tricouche ----
  parameter Real e_blk = 0.20, lam_blk = 0.95 "parpaing creux 20 cm";
  parameter Real rhoc_blk = 1300*1000, rhoc_iso = 30*1030;
  parameter Real hi = 7.7, he = 25;
  parameter Real ei = max(e_iti, 1e-4), ee = max(e_ite, 1e-4);
  parameter Real Riti = ei/(lam_iso*Awall);
  parameter Real Rblk = e_blk/(lam_blk*Awall);
  parameter Real Rite = ee/(lam_iso*Awall);
  parameter Real Rsi = 1/(hi*Awall) + Riti/4;
  parameter Real R12 = Riti/2, R23 = Riti/4 + Rblk/4, R34 = Rblk/2;
  parameter Real R45 = Rblk/4 + Rite/4, R56 = Rite/2;
  parameter Real R6e = Rite/4 + 1/(he*Awall);
  parameter Real C1 = rhoc_iso*ei/2*Awall,  C2 = C1;
  parameter Real C3 = rhoc_blk*e_blk/2*Awall, C4 = C3;
  parameter Real C5 = rhoc_iso*ee/2*Awall,  C6 = C5;

  // ---- Regulations ----
  parameter Real Tset_h = 292.15 "consigne chauffage 19 C";
  parameter Real Tset_c = 299.15 "consigne rafraichissement 26 C";
  parameter Real Kp = 4000, Kc = 4000;
  parameter Real fanWhm3 = 0.15;
  parameter Real Ppv_kWc = 3.0 "puissance crete PV installee, FIXE [kWc]";
  parameter Real PR_pv = 0.90 "ratio de performance global (cf. documentation)";

  // ---- Meteo ----
  Modelica.Blocks.Sources.CombiTimeTable tmy(
    tableOnFile = true, tableName = "tmy", fileName = "weather.txt",
    columns = {2, 3},
    smoothness = Modelica.Blocks.Types.Smoothness.LinearSegments,
    extrapolation = Modelica.Blocks.Types.Extrapolation.Periodic);
  Real Tout = tmy.y[1] + dTout;
  Real Qsol = fsol*0.5*Awin*tmy.y[2];

  // ---- Ventilation adaptative (rampes continues anti-broutement) ----
  Real hour = mod(time/3600, 24);
  Real night = (if hour > 22 or hour < 7 then 1.0 else 0.0);
  Real needCool = max(0, min(1, (Tair - 297.15)/2));
  Real vfrac = max(0, min(1, (Tair - Tout - 0.5)/1.5));
  Real vopen = max(0, min(1, (Tair - 299.15)/1.5))*vfrac*ach_day;
  Real boostN = night*needCool*vfrac*ach_night;
  Real UAv = (ach + boostN + vopen)*V*0.34;

  // ---- Chauffage / refroidissement ----
  Real Qheat = min(Pheat, max(0, Kp*(Tset_h - Tair)));
  Real Qcool = min(Pcool, max(0, Kc*(Tair - Tset_c)));
  Real Pelec = Qheat + Qcool/seer + boostN*V*fanWhm3 "charge electrique totale (chauffage resistif + PAC froid + ventilateurs) [W]";
  Real Ppv = Ppv_kWc*1000*(tmy.y[2]/1000)*PR_pv "production PV instantanee [W]";
  Real Pgrid_cool = max(Pelec - Ppv, 0) "import reseau residuel (chauffage + froid), apres autoconso PV [W]";
  Real Pself_cool = min(Pelec, Ppv) "autoconsommation directe [W]";
  Real Pexport = max(Ppv - Pelec, 0) "surplus PV injecte au reseau [W]";

  // ---- Etats ----
  Real Tair(start = 285.15, fixed = true);
  Real T1(start = 284.9, fixed = true),  T2(start = 284.6, fixed = true);
  Real T3(start = 284.0, fixed = true),  T4(start = 283.2, fixed = true);
  Real T5(start = 282.5, fixed = true),  T6(start = 282.0, fixed = true);

  // ---- Indicateurs annuels (apres 14 j de mise en regime) ----
  Real meas = (if time > 14*86400 then 1.0 else 0.0);
  Real Eheat(start = 0, fixed = true) "chauffage, demande thermique BRUTE avant PV [kWh/an]";
  Real Ecool(start = 0, fixed = true) "electricite BRUTE totale (chauffage+froid+ventilateurs) [kWh/an] (hors PV)";
  Real Egrid_total(start = 0, fixed = true) "electricite NETTE reseau (chauffage+froid), apres autoconso PV [kWh/an]";
  Real Eself_cool(start = 0, fixed = true) "autoconsommation PV directe (chauffage+froid) [kWh/an]";
  Real Eexport(start = 0, fixed = true) "surplus PV exporte au reseau [kWh/an]";
  // Tmin_hiver et Tmax_ete sont extraits de la colonne Tair du CSV par fz
  // (expressions 'python:'), la fenetre de mesure excluant la mise en regime.

equation
  Cair*der(Tair) = (T1 - Tair)/Rsi + (UAv + UAother)*(Tout - Tair)
                   + Qheat - Qcool + Qint + Qsol;
  C1*der(T1) = (Tair - T1)/Rsi + (T2 - T1)/R12;
  C2*der(T2) = (T1 - T2)/R12 + (T3 - T2)/R23;
  C3*der(T3) = (T2 - T3)/R23 + (T4 - T3)/R34;
  C4*der(T4) = (T3 - T4)/R34 + (T5 - T4)/R45;
  C5*der(T5) = (T4 - T5)/R45 + (T6 - T5)/R56;
  C6*der(T6) = (T5 - T6)/R56 + (Tout - T6)/R6e;
  der(Eheat) = meas*Qheat/3.6e6;
  der(Ecool) = meas*Pelec/3.6e6;
  der(Egrid_total) = meas*Pgrid_cool/3.6e6;
  der(Eself_cool) = meas*Pself_cool/3.6e6;
  der(Eexport) = meas*Pexport/3.6e6;

  annotation(experiment(StopTime = 32745600, Tolerance = 1e-6, Interval = 3600));
end BuildingTherm;
