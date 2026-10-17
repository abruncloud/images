package main

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestConnectionRequiresTLSIdentityVerification(t *testing.T) {
	for _, security := range []string{"<secure>false</secure>", "<secure>true</secure><openSSL><client><verificationMode>none</verificationMode></client></openSSL>"} {
		file := filepath.Join(t.TempDir(), "connection.xml")
		if err := os.WriteFile(file, []byte("<config><host>server</host><port>9440</port><user>backup</user>"+security+"</config>"), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := readConfig(file); err == nil {
			t.Fatal("insecure connection configuration accepted")
		}
	}
}
func TestConnectionEscapingAndCAIdentity(t *testing.T) {
	file := filepath.Join(t.TempDir(), "connection.xml")
	xml := "<config><host>server.example</host><port>9440</port><user>backup</user><password>a&lt;&amp;b</password><secure>true</secure><openSSL><client><verificationMode>strict</verificationMode></client></openSSL></config>"
	if err := os.WriteFile(file, []byte(xml), 0600); err != nil {
		t.Fatal(err)
	}
	c, err := readConfig(file)
	if err != nil {
		t.Fatal(err)
	}
	if c.Password != "a<&b" || c.Database != "default" {
		t.Fatal("escaped credentials/default database changed")
	}
	tls, err := tlsConfig(c)
	if err != nil {
		t.Fatal(err)
	}
	if tls.InsecureSkipVerify || tls.ServerName != "server.example" {
		t.Fatal("TLS peer identity is not verified")
	}
}
func TestConfigInputIsBounded(t *testing.T) {
	file := filepath.Join(t.TempDir(), "connection.xml")
	if err := os.WriteFile(file, []byte(strings.Repeat("x", (1<<20)+1)), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := readConfig(file); err == nil || !strings.Contains(err.Error(), "exceeds") {
		t.Fatal("oversized configuration accepted")
	}
}

func TestNullableScalarOutput(t *testing.T) {
	value := uint64(42)
	if formatValue(reflect.ValueOf(&value)) != "42" {
		t.Fatal("nullable value was printed as a pointer")
	}
	var absent *uint64
	if formatValue(reflect.ValueOf(absent)) != `\N` {
		t.Fatal("null output is not explicit")
	}
}
