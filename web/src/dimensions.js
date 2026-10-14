export const dimensionNames={P:'规划',R:'反应',G:'引导',O:'开放',M:'机制',N:'叙事',H:'高压',C:'舒缓',SOLO:'独玩',SOCIAL:'社交',COMP:'竞争',COOP:'合作'};
export const dimensionCodes={P:'PLAN',R:'REACT',G:'GUIDE',O:'OPEN',M:'MECH',N:'NARR',H:'HARD',C:'CALM',SOLO:'SOLO',SOCIAL:'SOCIAL',COMP:'COMP',COOP:'COOP'};
export const displayCode=code=>dimensionCodes[code]||code;
export const displayType=type=>type?Array.from(type).map(displayCode).join(' · '):null;
