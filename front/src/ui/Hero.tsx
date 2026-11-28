import type { ComponentChildren } from "preact";
import { HeroArt, Icon, type IconName } from "./Icon";

export interface HeroStat {
  value: ComponentChildren;
  label: ComponentChildren;
}

export interface HeroFact {
  label: ComponentChildren;
  value: ComponentChildren;
  mono?: boolean;
}

export interface HeroProps {
  eyebrow?: ComponentChildren;
  title: ComponentChildren;
  badge?: ComponentChildren;
  facts?: HeroFact[];
  lead?: ComponentChildren[];
  stats?: HeroStat[];
  icon?: IconName;
  art?: boolean;
  actions?: ComponentChildren;
}

export function Hero({ eyebrow, title, badge, facts = [], lead = [], stats = [], icon, art, actions }: HeroProps) {
  return (
    <header class="hero">
      <div class="page-wrap hero-inner">
        <div class="hero-main">
          {icon && <span class="hero-icon"><Icon name={icon} size={38} /></span>}
          <div class="hero-text">
            {eyebrow && <span class="hero-eyebrow">{eyebrow}</span>}
            {badge ? <div class="hero-titled"><h1 class="hero-title">{title}</h1>{badge}</div> : <h1 class="hero-title">{title}</h1>}
            {lead.map((line, index) => <p class="hero-lead" key={index}>{line}</p>)}
            {stats.length > 0 && (
              <div class="hero-stats">
                {stats.map((stat, index) => <span class="hero-stat" key={index}><b>{stat.value}</b><span>{stat.label}</span></span>)}
              </div>
            )}
          </div>
        </div>
        {facts.length > 0 && (
          <dl class="hero-facts">
            {facts.map((fact, index) => (
              <div class="hero-fact" key={index}>
                <dt class="label">{fact.label}</dt>
                <dd class={fact.mono ? "hero-fact-value is-mono" : "hero-fact-value"}>{fact.value}</dd>
              </div>
            ))}
          </dl>
        )}
        {art && <HeroArt />}
        {actions && <div class="hero-actions">{actions}</div>}
      </div>
    </header>
  );
}
