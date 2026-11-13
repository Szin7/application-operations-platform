package main

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/prometheus/procfs"
)

// Keep the raw space in the 9p super options: it caused the lab failure.
func TestWSLMountinfo(t *testing.T) {
	root := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, "1"), 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "1", "mountinfo")
	fixture := `351 333 8:80 / / rw,relatime - ext4 /dev/sdf rw,discard,errors=remount-ro,data=ordered
403 351 0:115 / /mnt/d rw,noatime - 9p D:\134 rw,aname=drvfs;path=D:\;uid=1000;gid=1000;symlinkroot=/mnt/,cache=5,access=client,msize=65536,trans=fd,rfd=6,wfd=6
404 351 0:116 / /Docker/host rw,noatime - 9p C:\134Program\040Files\134Docker\134Docker\134resources rw,aname=drvfs;path=C:\Program Files\Docker\Docker\resources;symlinkroot=/mnt/,cache=5,access=client,msize=65536,trans=fd,rfd=3,wfd=3
`
	if err := os.WriteFile(path, []byte(fixture), 0600); err != nil {
		t.Fatal(err)
	}
	fs, err := procfs.NewFS(root)
	if err != nil {
		t.Fatal(err)
	}
	mounts, err := fs.GetProcMounts(1)
	if err != nil {
		t.Fatalf("WSL mount information must parse: %v", err)
	}
	if len(mounts) != 3 {
		t.Fatalf("got %d mounts, want 3", len(mounts))
	}
	if mounts[0].Source != "/dev/sdf" || mounts[0].FSType != "ext4" || mounts[0].MountPoint != "/" {
		t.Fatalf("unexpected root mount: %+v", mounts[0])
	}
	if mounts[1].Source != `D:\134` || mounts[1].FSType != "9p" || mounts[1].MountPoint != "/mnt/d" {
		t.Fatalf("unexpected Windows drive mount: %+v", mounts[1])
	}
	if mounts[2].SuperOptions["aname"] != `drvfs;path=C:\Program Files\Docker\Docker\resources;symlinkroot=/mnt/` {
		t.Fatalf("super options lost data: %+v", mounts[2].SuperOptions)
	}
	if err := os.WriteFile(path, []byte("not a valid mount record\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := fs.GetProcMounts(1); err == nil {
		t.Fatal("malformed mount records must still fail")
	}
}
