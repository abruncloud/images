// clickhouse-sql is a small native-protocol SQL client, not clickhouse-client.
package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/xml"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"os/signal"
	"reflect"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/ClickHouse/clickhouse-go/v2"
)

const version = "1.0.0"
const driverVersion = "2.49.0"
const outputLimit = 8 << 20

type configuration struct {
	Host     string `xml:"host"`
	Port     int    `xml:"port"`
	User     string `xml:"user"`
	Password string `xml:"password"`
	Database string `xml:"database"`
	Secure   bool   `xml:"secure"`
	SSL      struct {
		Client struct {
			CA           string `xml:"caConfig"`
			Verification string `xml:"verificationMode"`
			ServerName   string `xml:"serverName"`
		} `xml:"client"`
	} `xml:"openSSL"`
}

func readConfig(path string) (configuration, error) {
	var c configuration
	f, err := os.Open(path)
	if err != nil {
		return c, err
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, (1<<20)+1))
	if err != nil {
		return c, err
	}
	if len(data) > 1<<20 {
		return c, errors.New("configuration exceeds 1 MiB")
	}
	if err = xml.Unmarshal(data, &c); err != nil {
		return c, errors.New("invalid XML configuration")
	}
	if c.Host == "" || c.Port < 1 || c.Port > 65535 || c.User == "" {
		return c, errors.New("host, port and user are required")
	}
	if !c.Secure || c.SSL.Client.Verification != "strict" {
		return c, errors.New("secure=true and strict certificate verification are required")
	}
	if c.Database == "" {
		c.Database = "default"
	}
	return c, nil
}

func tlsConfig(c configuration) (*tls.Config, error) {
	roots, err := x509.SystemCertPool()
	if err != nil {
		return nil, err
	}
	if c.SSL.Client.CA != "" {
		pem, err := os.ReadFile(c.SSL.Client.CA)
		if err != nil {
			return nil, err
		}
		roots = x509.NewCertPool()
		if !roots.AppendCertsFromPEM(pem) {
			return nil, errors.New("CA file contains no certificates")
		}
	}
	name := c.SSL.Client.ServerName
	if name == "" {
		name = c.Host
	}
	return &tls.Config{MinVersion: tls.VersionTLS12, RootCAs: roots, ServerName: name}, nil
}

func run(ctx context.Context, c configuration, query, queryID string, execute bool, timeout time.Duration, out io.Writer) error {
	tc, err := tlsConfig(c)
	if err != nil {
		return err
	}
	conn, err := clickhouse.Open(&clickhouse.Options{
		Addr: []string{net.JoinHostPort(c.Host, strconv.Itoa(c.Port))},
		Auth: clickhouse.Auth{Database: c.Database, Username: c.User, Password: c.Password}, TLS: tc,
		DialTimeout: 10 * time.Second, ReadTimeout: timeout, MaxOpenConns: 1, MaxIdleConns: 1,
		ClientInfo: clickhouse.ClientInfo{Products: []struct{ Name, Version string }{{"clickhouse-sql", version}}},
	})
	if err != nil {
		return err
	}
	defer conn.Close()
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	ctx = clickhouse.Context(ctx, clickhouse.WithQueryID(queryID))
	if execute {
		return conn.Exec(ctx, query)
	}
	rows, err := conn.Query(ctx, query)
	if err != nil {
		return err
	}
	defer rows.Close()
	columns := rows.ColumnTypes()
	written := 0
	for rows.Next() {
		values := make([]any, len(columns))
		for i, col := range columns {
			values[i] = reflect.New(col.ScanType()).Interface()
		}
		if err := rows.Scan(values...); err != nil {
			return err
		}
		fields := make([]string, len(values))
		for i, v := range values {
			fields[i] = formatValue(reflect.ValueOf(v).Elem())
		}
		line := strings.Join(fields, "\t") + "\n"
		if len(line) > outputLimit-written {
			return errors.New("query output exceeds 8 MiB")
		}
		n, err := io.WriteString(out, line)
		written += n
		if err != nil {
			return err
		}
	}
	return rows.Err()
}

func formatValue(value reflect.Value) string {
	for value.Kind() == reflect.Pointer || value.Kind() == reflect.Interface {
		if value.IsNil() {
			return `\N`
		}
		value = value.Elem()
	}
	if b, ok := value.Interface().([]byte); ok {
		return string(b)
	}
	return fmt.Sprint(value.Interface())
}

func main() {
	config := flag.String("config-file", "", "private XML connection configuration")
	query := flag.String("query", "", "one SQL statement")
	queryID := flag.String("query_id", "", "query identity for observation and cancellation")
	timeout := flag.Duration("timeout", 30*time.Second, "execution deadline, maximum 1h")
	execute := flag.Bool("exec", false, "execute a statement that returns no rows, e.g. CREATE or INSERT")
	showVersion := flag.Bool("version", false, "print tool and official driver versions")
	flag.Parse()
	if *showVersion {
		fmt.Printf("clickhouse-sql %s (official clickhouse-go/v2 %s)\n", version, driverVersion)
		return
	}
	if flag.NArg() != 0 || *config == "" || *query == "" || *timeout <= 0 || *timeout > time.Hour {
		fmt.Fprintln(os.Stderr, "require --config-file, --query and timeout in (0,1h]")
		os.Exit(2)
	}
	c, err := readConfig(*config)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err == nil {
		err = run(ctx, c, *query, *queryID, *execute, *timeout, os.Stdout)
	}
	if err != nil {
		message := err.Error()
		if c.Password != "" {
			message = strings.ReplaceAll(message, c.Password, "[redacted]")
		}
		fmt.Fprintln(os.Stderr, message)
		os.Exit(1)
	}
}
