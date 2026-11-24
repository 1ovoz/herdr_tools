import { View, div } from "gpui-kit";
import { props, theme } from "herdr";

export default class KitVersion extends View {
  render() {
    const t = theme();
    const version = props()?.version;
    return div().size_full().flex().items_center().justify_center().bg(t.chrome)
      .border_t(1).border_color(t.border).text_color(t.muted).text_size(10)
      .child(version ? `mod ${version}` : "");
  }
}
