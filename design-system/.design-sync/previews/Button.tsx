import { Button } from "@stewie/design-system";

export const Primary = () => <Button variant="primary" icon="play">Execute plan</Button>;
export const Ghost = () => <Button variant="ghost" icon="download">Export Plan IR</Button>;
export const Danger = () => <Button variant="danger" icon="safe-stop">Safe-stop</Button>;
export const Small = () => <Button size="sm" icon="target">Pick site</Button>;
export const Disabled = () => <Button disabled>Disabled</Button>;
