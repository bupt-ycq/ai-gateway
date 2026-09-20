package model

import (
	"errors"

	"github.com/google/uuid"
	"gorm.io/gorm"
)

// DemoPaymentOrder is a separate simulation ledger. It must never be converted
// into a TopUp or used to fund User.Quota or a subscription.
type DemoPaymentOrder struct {
	ID            int    `json:"-" gorm:"primaryKey"`
	OrderNo       string `json:"order_no" gorm:"type:varchar(64);uniqueIndex"`
	UserID        int    `json:"-" gorm:"index"`
	AmountCents   int64  `json:"amount_cents"`
	PaymentMethod string `json:"payment_method" gorm:"type:varchar(16)"`
	Status        string `json:"status" gorm:"type:varchar(16)"`
	CreatedAt     int64  `json:"created_at" gorm:"autoCreateTime:false"`
	ExpiresAt     int64  `json:"expires_at"`
	ResolvedAt    int64  `json:"resolved_at"`
}

var (
	ErrDemoPaymentAmount  = errors.New("Demo amount must be between 100 and 100000 cents")
	ErrDemoPaymentMethod  = errors.New("Demo payment method must be alipay or wxpay")
	ErrDemoPaymentOutcome = errors.New("Demo outcome must be success, failed or cancelled")
)

func CreateDemoPaymentOrder(userID int, amountCents int64, method string, now int64) (*DemoPaymentOrder, error) {
	if amountCents < 100 || amountCents > 100000 {
		return nil, ErrDemoPaymentAmount
	}
	if method != "alipay" && method != "wxpay" {
		return nil, ErrDemoPaymentMethod
	}
	order := &DemoPaymentOrder{
		OrderNo: "demo_" + uuid.NewString(), UserID: userID,
		AmountCents: amountCents, PaymentMethod: method, Status: "pending",
		CreatedAt: now, ExpiresAt: now + 600,
	}
	if err := DB.Create(order).Error; err != nil {
		return nil, err
	}
	return order, nil
}

func expireDemoPaymentOrders(userID int, now int64) error {
	return DB.Model(&DemoPaymentOrder{}).
		Where("user_id = ? AND status = ? AND expires_at <= ?", userID, "pending", now).
		Updates(map[string]interface{}{"status": "expired", "resolved_at": gorm.Expr("expires_at")}).Error
}

func GetDemoPaymentBalance(userID int) (int64, error) {
	var balance int64
	err := DB.Model(&DemoPaymentOrder{}).Where("user_id = ? AND status = ?", userID, "success").
		Select("COALESCE(SUM(amount_cents), 0)").Scan(&balance).Error
	return balance, err
}

func GetDemoPaymentOrders(userID int, now int64) ([]DemoPaymentOrder, error) {
	if err := expireDemoPaymentOrders(userID, now); err != nil {
		return nil, err
	}
	orders := make([]DemoPaymentOrder, 0)
	err := DB.Where("user_id = ?", userID).Order("id DESC").Limit(20).Find(&orders).Error
	return orders, err
}

func ResolveDemoPaymentOrder(userID int, orderNo string, outcome string, now int64) (*DemoPaymentOrder, error) {
	if outcome != "success" && outcome != "failed" && outcome != "cancelled" {
		return nil, ErrDemoPaymentOutcome
	}
	if err := expireDemoPaymentOrders(userID, now); err != nil {
		return nil, err
	}
	// The conditional write is the settlement: there is no separate balance to
	// increment. Concurrent or repeated resolutions can only settle a row once.
	err := DB.Model(&DemoPaymentOrder{}).
		Where("user_id = ? AND order_no = ? AND status = ? AND expires_at > ?", userID, orderNo, "pending", now).
		Updates(map[string]interface{}{"status": outcome, "resolved_at": now}).Error
	if err != nil {
		return nil, err
	}
	var order DemoPaymentOrder
	if err := DB.Where("user_id = ? AND order_no = ?", userID, orderNo).First(&order).Error; err != nil {
		return nil, err
	}
	return &order, nil
}
