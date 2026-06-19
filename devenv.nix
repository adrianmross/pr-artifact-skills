{ pkgs, ... }:

let
  python = pkgs.python3.withPackages (ps: [
    ps.pyyaml
  ]);
in
{
  packages = with pkgs; [
    bash
    coreutils
    git
    gh
    gnumake
    imagemagick
    jq
    nodejs_22
    python
    ripgrep
  ];

  enterShell = ''
    export PYTHON="${python}/bin/python3"

    if [ -n "''${NODE_EXTRA_CA_CERTS:-}" ] && [ ! -f "$NODE_EXTRA_CA_CERTS" ]; then
      unset NODE_EXTRA_CA_CERTS
    fi

    echo "pr-artifact-skills dev shell"
    echo "  devenv test"
    echo "  devenv tasks run plugin:validate"
    echo "  devenv tasks run skills:list"
    echo "  devenv tasks run demo:gif"
  '';

  tasks = {
    "test:unit".exec = "make test";

    "plugin:validate".exec = ''
      ./scripts/validate-plugin.sh
    '';

    "skills:list".exec = ''
      npx skills add . --list --full-depth --yes
    '';

    "demo:gif".exec = ''
      ./scripts/render-demo-gif.sh
    '';

    "release:package".exec = ''
      ./scripts/package-release.sh "v$(cat VERSION)"
    '';

    "dev:validate".exec = ''
      devenv tasks run test:unit
      devenv tasks run plugin:validate
      devenv tasks run skills:list
    '';
  };

  enterTest = ''
    devenv tasks run dev:validate
  '';
}
