import raw from './companies.json';

export interface SimextUnit {
  uid: string;
  name: string;
  make?: string;
  vehicle_model?: string;
  platform_id?: number;
  [key: string]: unknown;
}

export interface SimextCompany {
  id: string;
  name: string;
  about?: string;
  platform: 'traccar' | 'wialon' | 'aemp' | 'gateway';
  platform_label?: string;
  base_url: string;
  oem?: string;
  units: SimextUnit[];
}

export const COMPANIES = (raw as { companies: SimextCompany[] }).companies;

/** Companies whose platform is emulated here (Traccar is a real external server, gateway is local). */
export const SIMEXT_COMPANIES = COMPANIES.filter((c) => c.platform === 'wialon' || c.platform === 'aemp');

export const simextCompany = (id: string): SimextCompany | undefined => SIMEXT_COMPANIES.find((c) => c.id === id);

export const simextHosts = new Map(SIMEXT_COMPANIES.map((c) => [new URL(c.base_url).host, c] as const));
