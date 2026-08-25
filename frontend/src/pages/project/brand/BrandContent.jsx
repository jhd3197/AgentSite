import { useState } from "react";
import { Palette } from "@phosphor-icons/react";
import * as projectsApi from "../../../api/projects";
import Panel from "../../../components/ui/Panel";
import SectionHeader from "../../../components/ui/SectionHeader";
import TextField from "../../../components/ui/TextField";
import ColorField from "../../../components/ui/ColorField";
import Button from "../../../components/ui/Button";
import FileUpload from "./FileUpload";
import LayoutThumb from "./LayoutThumb";
import OptionCards from "./OptionCards";
import { DEFAULT_STYLE_SPEC, buildSpecFromProject } from "./tokens";

const COLOR_FIELDS = [
  ["primary_color", "Primary"],
  ["secondary_color", "Secondary"],
  ["accent_color", "Accent"],
  ["background_color", "Background"],
  ["surface_color", "Surface"],
  ["text_color", "Text"],
  ["text_secondary_color", "Text Secondary"],
  ["border_color", "Border"],
];

const TYPE_SCALE = ["sm", "base", "lg", "xl", "2xl", "3xl", "4xl"];
const WEIGHTS_RHYTHM = [
  ["font_weight_normal", "Normal"],
  ["font_weight_medium", "Medium"],
  ["font_weight_bold", "Bold"],
  ["line_height", "Line Height"],
  ["letter_spacing", "Letter Spacing"],
];
const SPACING_SCALE = [
  ["spacing_xs", "xs"],
  ["spacing_sm", "sm"],
  ["spacing_md", "md"],
  ["spacing_unit", "Base"],
  ["spacing_lg", "lg"],
  ["spacing_xl", "xl"],
  ["spacing_2xl", "2xl"],
];
const BORDER_FIELDS = [
  ["border_radius_sm", "sm"],
  ["border_radius", "Default"],
  ["border_radius_lg", "lg"],
  ["border_radius_full", "Full"],
  ["border_width", "Border Width"],
];
const SHADOW_FIELDS = [
  ["shadow_sm", "Small"],
  ["shadow_md", "Medium"],
  ["shadow_lg", "Large"],
];
const EFFECT_FIELDS = [
  ["transition_speed", "Transition Speed"],
  ["backdrop_blur", "Backdrop Blur"],
];

const LAYOUT_OPTIONS = [
  { value: "top-nav", label: "Top Nav", desc: "Horizontal menu at the top" },
  { value: "sidebar", label: "Sidebar", desc: "Vertical menu on the left" },
  { value: "minimal", label: "Minimal", desc: "Hamburger menu, clean look" },
  { value: "centered", label: "Centered", desc: "Logo center, links split" },
];
const NAV_POSITION_OPTIONS = [
  { value: "sticky", label: "Sticky", desc: "Stays visible on scroll" },
  { value: "fixed", label: "Fixed", desc: "Always at the top" },
  { value: "static", label: "Static", desc: "Scrolls with the page" },
];
const FOOTER_OPTIONS = [
  { value: "standard", label: "Standard", desc: "Links, logo, copyright" },
  { value: "minimal", label: "Minimal", desc: "Copyright line only" },
  { value: "none", label: "None", desc: "No footer" },
];

function FieldGrid({ fields, spec, setField, cols = "" }) {
  return (
    <div className={cols || "grid grid-cols-3 sm:grid-cols-5 gap-3"}>
      {fields.map(([key, label]) => (
        <TextField
          key={key}
          label={label}
          mono
          value={spec[key]}
          onChange={setField(key)}
        />
      ))}
    </div>
  );
}

function SubLabel({ children }) {
  return <p className="text-xs font-medium text-slate-400 mb-3">{children}</p>;
}

export default function BrandContent({ project, refresh }) {
  const [spec, setSpec] = useState(() => buildSpecFromProject(project?.style_spec));
  const [logoUrl, setLogoUrl] = useState(project?.logo_url || "");
  const [iconUrl, setIconUrl] = useState(project?.icon_url || "");
  const [saving, setSaving] = useState(false);
  const [initialized, setInitialized] = useState(!!project?.style_spec);

  const setField = (key) => (value) => setSpec((s) => ({ ...s, [key]: value }));

  const handleSetupBrand = async () => {
    setSaving(true);
    try {
      await projectsApi.updateProject(project.id, {
        style_spec: DEFAULT_STYLE_SPEC,
      });
      setSpec(DEFAULT_STYLE_SPEC);
      setInitialized(true);
      refresh();
    } catch (err) {
      console.error("Failed to set up brand:", err);
    } finally {
      setSaving(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await projectsApi.updateProject(project.id, {
        logo_url: logoUrl,
        icon_url: iconUrl,
        style_spec: spec,
      });
      refresh();
    } catch (err) {
      console.error("Failed to save brand:", err);
    } finally {
      setSaving(false);
    }
  };

  const handleLogoUpload = async (path) => {
    setLogoUrl(path);
    try {
      await projectsApi.updateProject(project.id, { logo_url: path });
      refresh();
    } catch (err) {
      console.error("Failed to save logo:", err);
    }
  };

  const handleIconUpload = async (path) => {
    setIconUrl(path);
    try {
      await projectsApi.updateProject(project.id, { icon_url: path });
      refresh();
    } catch (err) {
      console.error("Failed to save icon:", err);
    }
  };

  if (!project?.style_spec && !initialized) {
    return (
      <div className="max-w-2xl">
        <Panel className="p-8 text-center">
          <Palette className="text-slate-600 mx-auto mb-4" size={48} />
          <h3 className="text-white font-semibold mb-2">No Brand Identity Yet</h3>
          <p className="text-sm text-slate-500 mb-6">
            Set up your brand to define the complete design system — colors,
            typography, layout, spacing, borders, shadows, and more.
          </p>
          <Button variant="brand" size="lg" onClick={handleSetupBrand} disabled={saving}>
            {saving ? "Setting up..." : "Set Up Brand"}
          </Button>
        </Panel>
      </div>
    );
  }

  return (
    <div className="space-y-10 max-w-3xl pb-12">
      <section>
        <SectionHeader
          title="Logo & Icon"
          description="Brand marks used in headers, favicons, and social previews."
        />
        <div className="grid grid-cols-2 gap-6">
          <FileUpload
            label="Project Logo"
            currentUrl={logoUrl}
            onUpload={handleLogoUpload}
            projectId={project.id}
          />
          <FileUpload
            label="Favicon / Icon"
            currentUrl={iconUrl}
            onUpload={handleIconUpload}
            projectId={project.id}
          />
        </div>
      </section>

      <hr className="border-slate-800" />

      <section>
        <SectionHeader
          title="Colors"
          description="Core palette applied to backgrounds, text, borders, and interactive elements."
        />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {COLOR_FIELDS.map(([key, label]) => (
            <ColorField key={key} label={label} value={spec[key]} onChange={setField(key)} />
          ))}
        </div>
      </section>

      <hr className="border-slate-800" />

      <section>
        <SectionHeader
          title="Typography"
          description="Font families, sizes, weights, and line height for the type scale."
        />
        <div className="space-y-5">
          <div>
            <SubLabel>Font Families</SubLabel>
            <div className="grid grid-cols-3 gap-4">
              <TextField label="Heading" value={spec.font_heading} onChange={setField("font_heading")} />
              <TextField label="Body" value={spec.font_body} onChange={setField("font_body")} />
              <TextField label="Monospace" value={spec.font_mono} onChange={setField("font_mono")} />
            </div>
          </div>
          <div>
            <SubLabel>Type Scale</SubLabel>
            <div className="grid grid-cols-4 sm:grid-cols-7 gap-3">
              {TYPE_SCALE.map((step) => (
                <TextField
                  key={step}
                  label={step}
                  mono
                  value={spec[`font_size_${step}`]}
                  onChange={setField(`font_size_${step}`)}
                />
              ))}
            </div>
          </div>
          <div>
            <SubLabel>Weights & Rhythm</SubLabel>
            <FieldGrid fields={WEIGHTS_RHYTHM} spec={spec} setField={setField} />
          </div>
        </div>
      </section>

      <hr className="border-slate-800" />

      <section>
        <SectionHeader
          title="Layout"
          description="Choose how the site is structured — navigation placement, behavior, and page dimensions."
        />
        <div className="space-y-5">
          <div>
            <SubLabel>Navigation Style</SubLabel>
            <OptionCards
              options={LAYOUT_OPTIONS}
              value={spec.layout_style}
              onChange={setField("layout_style")}
              renderThumb={(val, active) => (
                <LayoutThumb type={val} active={active} />
              )}
            />
          </div>
          <div>
            <SubLabel>Navigation Behavior</SubLabel>
            <OptionCards
              options={NAV_POSITION_OPTIONS}
              value={spec.nav_position}
              onChange={setField("nav_position")}
            />
          </div>
          <div>
            <SubLabel>Footer</SubLabel>
            <OptionCards
              options={FOOTER_OPTIONS}
              value={spec.footer_style}
              onChange={setField("footer_style")}
            />
          </div>
          <div>
            <SubLabel>Dimensions</SubLabel>
            <div className="grid grid-cols-3 gap-4">
              <TextField label="Max Width" mono value={spec.max_width} onChange={setField("max_width")} />
              <TextField label="Container Padding" mono value={spec.container_padding} onChange={setField("container_padding")} />
              <TextField label="Section Gap" mono value={spec.section_gap} onChange={setField("section_gap")} />
            </div>
          </div>
        </div>
      </section>

      <hr className="border-slate-800" />

      <section>
        <SectionHeader
          title="Spacing"
          description="Consistent spacing scale used for margins, padding, and gaps."
        />
        <div className="grid grid-cols-4 sm:grid-cols-7 gap-3">
          {SPACING_SCALE.map(([key, label]) => (
            <TextField key={key} label={label} mono value={spec[key]} onChange={setField(key)} />
          ))}
        </div>
      </section>

      <hr className="border-slate-800" />

      <section>
        <SectionHeader
          title="Borders"
          description="Border radii and widths for cards, buttons, inputs, and containers."
        />
        <FieldGrid fields={BORDER_FIELDS} spec={spec} setField={setField} />
      </section>

      <hr className="border-slate-800" />

      <section>
        <SectionHeader
          title="Shadows"
          description="Elevation levels for cards, dropdowns, and modals."
        />
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {SHADOW_FIELDS.map(([key, label]) => (
            <TextField key={key} label={label} mono value={spec[key]} onChange={setField(key)} />
          ))}
        </div>
      </section>

      <hr className="border-slate-800" />

      <section>
        <SectionHeader
          title="Effects"
          description="Transitions and visual effects applied globally."
        />
        <div className="grid grid-cols-2 gap-4">
          {EFFECT_FIELDS.map(([key, label]) => (
            <TextField key={key} label={label} mono value={spec[key]} onChange={setField(key)} />
          ))}
        </div>
      </section>

      <div className="pt-4 border-t border-slate-800">
        <Button variant="primary" size="lg" onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : "Save Brand"}
        </Button>
      </div>
    </div>
  );
}
