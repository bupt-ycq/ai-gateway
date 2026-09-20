package model

import (
	"path/filepath"
	"sync"
	"testing"

	"github.com/glebarez/sqlite"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

func setupDemoPaymentDB(t *testing.T) {
	t.Helper()
	db, err := gorm.Open(sqlite.Open(filepath.Join(t.TempDir(), "demo.db")), &gorm.Config{})
	require.NoError(t, err)
	sqlDB, err := db.DB()
	require.NoError(t, err)
	sqlDB.SetMaxOpenConns(1)
	require.NoError(t, db.AutoMigrate(&DemoPaymentOrder{}, &User{}, &TopUp{}))
	previousDB := DB
	DB = db
	t.Cleanup(func() {
		DB = previousDB
		require.NoError(t, sqlDB.Close())
	})
}

func TestDemoPaymentValidation(t *testing.T) {
	setupDemoPaymentDB(t)
	for _, test := range []struct {
		name   string
		amount int64
		method string
		err    error
	}{
		{"negative", -100, "alipay", ErrDemoPaymentAmount},
		{"below minimum", 99, "alipay", ErrDemoPaymentAmount},
		{"above maximum", 100001, "wxpay", ErrDemoPaymentAmount},
		{"overflow sized amount", 9223372036854775807, "alipay", ErrDemoPaymentAmount},
		{"unknown method", 100, "stripe", ErrDemoPaymentMethod},
		{"missing method", 100, "", ErrDemoPaymentMethod},
	} {
		t.Run(test.name, func(t *testing.T) {
			order, err := CreateDemoPaymentOrder(1, test.amount, test.method, 1000)
			assert.ErrorIs(t, err, test.err)
			assert.Nil(t, order)
		})
	}
	var count int64
	require.NoError(t, DB.Model(&DemoPaymentOrder{}).Count(&count).Error)
	assert.Zero(t, count)
	for _, method := range []string{"alipay", "wxpay"} {
		order, err := CreateDemoPaymentOrder(1, 100000, method, 1000)
		require.NoError(t, err)
		assert.Equal(t, "pending", order.Status)
		assert.Equal(t, int64(1600), order.ExpiresAt)
	}
}

func TestDemoPaymentConcurrentSettlementDoesNotFundRealWallet(t *testing.T) {
	setupDemoPaymentDB(t)
	user := User{Username: "demo-only", Quota: 12345}
	require.NoError(t, DB.Create(&user).Error)
	order, err := CreateDemoPaymentOrder(user.Id, 2500, "alipay", 1000)
	require.NoError(t, err)
	start := make(chan struct{})
	errors := make(chan error, 2)
	var workers sync.WaitGroup
	for i := 0; i < 2; i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			<-start
			_, err := ResolveDemoPaymentOrder(user.Id, order.OrderNo, "success", 1001)
			errors <- err
		}()
	}
	close(start)
	workers.Wait()
	close(errors)
	for err := range errors {
		require.NoError(t, err)
	}
	resolved, err := ResolveDemoPaymentOrder(user.Id, order.OrderNo, "cancelled", 1002)
	require.NoError(t, err)
	assert.Equal(t, "success", resolved.Status)
	assert.Equal(t, int64(1001), resolved.ResolvedAt)
	balance, err := GetDemoPaymentBalance(user.Id)
	require.NoError(t, err)
	assert.Equal(t, int64(2500), balance)
	var persisted User
	require.NoError(t, DB.First(&persisted, user.Id).Error)
	assert.Equal(t, 12345, persisted.Quota)
	var topups int64
	require.NoError(t, DB.Model(&TopUp{}).Count(&topups).Error)
	assert.Zero(t, topups)
}

func TestDemoPaymentIsolationAndTerminalStates(t *testing.T) {
	setupDemoPaymentDB(t)
	for _, outcome := range []string{"failed", "cancelled", "expired"} {
		t.Run(outcome, func(t *testing.T) {
			order, err := CreateDemoPaymentOrder(1, 100, "wxpay", 1000)
			require.NoError(t, err)
			_, err = ResolveDemoPaymentOrder(2, order.OrderNo, "success", 1001)
			assert.ErrorIs(t, err, gorm.ErrRecordNotFound)
			_, err = ResolveDemoPaymentOrder(1, order.OrderNo, "bogus", 1001)
			assert.ErrorIs(t, err, ErrDemoPaymentOutcome)
			resolveAt, requested := int64(1001), outcome
			if outcome == "expired" {
				resolveAt, requested = order.ExpiresAt, "success"
			}
			resolved, err := ResolveDemoPaymentOrder(1, order.OrderNo, requested, resolveAt)
			require.NoError(t, err)
			assert.Equal(t, outcome, resolved.Status)
			assert.Equal(t, resolveAt, resolved.ResolvedAt)
			resolved, err = ResolveDemoPaymentOrder(1, order.OrderNo, "success", resolveAt+1)
			require.NoError(t, err)
			assert.Equal(t, outcome, resolved.Status)
		})
	}
	balance, err := GetDemoPaymentBalance(1)
	require.NoError(t, err)
	assert.Zero(t, balance)
	orders, err := GetDemoPaymentOrders(2, 2000)
	require.NoError(t, err)
	assert.Empty(t, orders)
	_, err = ResolveDemoPaymentOrder(1, "demo_missing", "success", 2000)
	assert.ErrorIs(t, err, gorm.ErrRecordNotFound)
}

func TestDemoPaymentHistoryExpiryAndBalanceBeyondPage(t *testing.T) {
	setupDemoPaymentDB(t)
	for i := 0; i < 21; i++ {
		order, err := CreateDemoPaymentOrder(1, 100, "alipay", int64(1000+i))
		require.NoError(t, err)
		_, err = ResolveDemoPaymentOrder(1, order.OrderNo, "success", int64(1000+i))
		require.NoError(t, err)
	}
	pending, err := CreateDemoPaymentOrder(1, 500, "wxpay", 1022)
	require.NoError(t, err)
	orders, err := GetDemoPaymentOrders(1, pending.ExpiresAt)
	require.NoError(t, err)
	require.Len(t, orders, 20)
	assert.Equal(t, pending.OrderNo, orders[0].OrderNo)
	assert.Equal(t, "expired", orders[0].Status)
	assert.Equal(t, pending.ExpiresAt, orders[0].ResolvedAt)
	balance, err := GetDemoPaymentBalance(1)
	require.NoError(t, err)
	assert.Equal(t, int64(2100), balance)
}
