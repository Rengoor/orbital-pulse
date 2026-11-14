// Vitalis: types as documentation. Global: window.Vitalis
export type Tier = 'GREEN' | 'YELLOW' | 'RED' | 'GREY';
export type Action = 'NO_ACTION' | 'RECHECK_IN_1H' | 'REST_AND_HYDRATE' | 'USE_PROTOCOL_CARD' | 'ALERT_CMO' | 'CONTACT_GROUND_URGENT';
export type Source = 'simulated' | 'nasa_osdr' | 'nasa_radlab' | 'nasa_donki' | 'manual';
export type ZoneId = 'neuro' | 'resp' | 'cardio' | 'radiation' | 'metabolic' | 'thermal' | 'msk';
export type IconName = 'clock' | 'drop' | 'card' | 'medic' | 'antenna' | 'check' | 'sun' | 'body' | 'helmet' | 'grid' | 'cube' | 'shield' | 'arrow' | 'flare' | 'tier-GREEN' | 'tier-YELLOW' | 'tier-RED' | 'tier-GREY';
export interface Provenance { dataset_id: string; field: string; timestamp?: string }

export interface BodyZone { id: ZoneId | string; tier: Tier; value: string | number | null; unit?: string; sub?: string; label?: string; x?: number; y?: number }
export interface BodyMapProps { zones: BodyZone[]; selected?: string | null; defaultSelected?: string | null; onSelect?: (id: string | null) => void; figure?: 'suit' | 'body'; animate?: boolean; ariaLabel?: string; className?: string; style?: object }
export interface VitalReadoutProps { label: string; value: string | number | null; unit?: string; tier: Tier; delta?: string; trend?: number[]; band?: [number, number]; source?: Source; dataset?: string; updated?: string; width?: number; selected?: boolean; onClick?: (e: any) => void; className?: string }
export interface SparklineProps { values: number[]; band?: [number, number]; tier?: Tier; width?: number; height?: number; label?: string; animate?: boolean }
export interface DoseGaugeProps { value: number; limit?: number; max?: number; rate?: number; event?: string | null; tier?: Tier; className?: string }
export interface DecisionCardProps { tier: Tier; headline: string; action: Action; reasons?: string[]; proposal?: { action: Action; by?: string }; provenance?: Provenance[]; simulated?: boolean; source?: Source; ts?: string; checkerVersion?: string; rulesetHash?: string; children?: any; className?: string }
export interface AdvisoryProps { text: string; status?: 'checked' | 'escalated' | 'blocked' | 'pending'; verdictNote?: string; stream?: boolean; model?: string; author?: string; className?: string }
export interface TierBadgeProps { tier: Tier; size?: 'md' | 'lg'; pulse?: boolean; label?: string; children?: any; className?: string }
export interface SourceLabelProps { source: Source; dataset?: string; className?: string }
export interface DelayDialProps { oneWaySeconds: number; vehicle?: string; groundTurnaroundSeconds?: number; blackout?: boolean; className?: string }
export interface CrewMember { id: string; name: string; role?: string; tier: Tier; initials?: string }
export interface CrewSwitcherProps { crew: CrewMember[]; value: string; onChange?: (id: string) => void; ariaLabel?: string }
export interface SegmentedControlProps { options: { value: string; label: string; icon?: IconName }[]; value?: string; defaultValue?: string; onChange?: (v: string) => void; ariaLabel?: string }
export interface ButtonProps { variant?: 'primary' | 'secondary' | 'ghost'; size?: 'md' | 'sm'; icon?: IconName; children?: any; [native: string]: any }
export interface PanelProps { title?: any; meta?: any; roomy?: boolean; plain?: boolean; scan?: boolean; style?: object; children?: any; className?: string }
